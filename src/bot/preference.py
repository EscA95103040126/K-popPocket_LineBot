"""AI 入坑：用 Gemini 把粉絲的偏好句解析成 JSON，在 v4 排序上加分、降權和排除。

解析結果只能用 data/curator/trait_tags.csv 裡的特質，每個特質對應到證據表
（data/curator/member_evidence.csv）裡有來源的主張，哪些成員有這個特質完全由證據決定，
模型不能替成員補特質。對應不到的說法放進 non_trait_constraints，不參與排序。

評估時解析結果從快取讀（以提示詞版本加問句的雜湊為 key），不即時呼叫模型，同一份快取
每次跑出來的分數都一樣。
"""

from __future__ import annotations

import csv
import hashlib
import json
import logging
import re
import time
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.bot.curator_query import CuratorQueryParser

logger = logging.getLogger(__name__)

TRAIT_TAGS_PATH = Path("data") / "curator" / "trait_tags.csv"
PREFERENCE_CACHE_PATH = Path("data") / "curator" / "llm_pref_cache.json"
PROMPT_VERSION = "pref-v6"
# 偏好解析固定用這個模型，不跟著 GEMINI_MODEL 換。test3（2026-10-29）用的是
# gemini-3.1-flash-lite-preview；preview 版停用後改用穩定版，練習集上的比較見 RESULTS_v5.md。
PREFERENCE_MODEL = "gemini-3.1-flash-lite"
RANKING_PERSPECTIVES = ("fan_perception", "press", "other_person")
# 程度詞對應的加權；分數單位是 v4 分數標準化後的標準差。
WEIGHTS = {"high": 1.0, "mid": 0.6, "low": 0.3}
# 在已用過的 dev＋test＋test2（137 題）上選的：加分 0.5→2.0 時外貌子集 lenient hit@3 從
# 0.350 升到 0.400，整體 strong hit@3 一直和 v4 持平。否定題太少，扣分沒辦法調，取中間值。
TRAIT_BONUS = 2.0
TRAIT_PENALTY = 1.0
GENDERS = ("female", "male")


@dataclass(frozen=True)
class TraitTag:
    tag: str
    label: str
    facets: frozenset[str]
    pattern: re.Pattern


@dataclass(frozen=True)
class Trait:
    tag: str
    raw: str
    polarity: str
    weight: str


@dataclass(frozen=True)
class Preference:
    is_appearance: bool = False
    gender: str | None = None
    traits: tuple[Trait, ...] = ()
    reference_member_ids: tuple[str, ...] = ()
    reference_out_of_catalog: tuple[str, ...] = ()
    exclude_artists: tuple[str, ...] = ()
    non_trait_constraints: tuple[str, ...] = ()

    def to_json(self) -> dict:
        return {
            "is_appearance": self.is_appearance,
            "gender": self.gender,
            "traits": [t.__dict__ for t in self.traits],
            "reference_member_ids": list(self.reference_member_ids),
            "reference_out_of_catalog": list(self.reference_out_of_catalog),
            "exclude_artists": list(self.exclude_artists),
            "non_trait_constraints": list(self.non_trait_constraints),
        }


def load_trait_tags(base_dir: Path) -> list[TraitTag]:
    path = base_dir / TRAIT_TAGS_PATH
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as file:
        return [
            TraitTag(
                row["tag"],
                row["label_zh"],
                frozenset(row["facets"].split("|")),
                re.compile(row["pattern"]),
            )
            for row in csv.DictReader(file)
        ]


def tag_members(
    tags: list[TraitTag], evidence: dict[str, list[dict[str, str]]]
) -> dict[str, frozenset[str]]:
    """每個特質有哪些成員：只看證據表裡有來源的主張。"""

    return {
        tag.tag: frozenset(
            member_id
            for member_id, rows in evidence.items()
            for row in rows
            if row.get("facet") in tag.facets
            and row.get("perspective") in RANKING_PERSPECTIVES
            and tag.pattern.search(row.get("value", ""))
        )
        for tag in tags
    }


def validate(
    data: dict, tags: list[TraitTag], members_by_id: dict[str, dict[str, str]]
) -> Preference:
    """把模型輸出整理成合法的偏好；不在特質表、不在目錄裡的東西都不拿來排序。"""

    known = {tag.tag for tag in tags}
    artists = {m["artist"].casefold(): m["artist"] for m in members_by_id.values()}
    traits, unmapped = [], []
    for item in data.get("traits") or []:
        if not isinstance(item, dict):
            continue
        tag, raw = str(item.get("tag", "")), str(item.get("raw", ""))
        if tag not in known:
            unmapped.append(f"unmapped:{raw or tag}")
            continue
        polarity = "-" if item.get("polarity") == "-" else "+"
        weight = item.get("weight") if item.get("weight") in WEIGHTS else "mid"
        traits.append(Trait(tag, raw, polarity, weight))
    references, outside = [], list(_strings(data.get("reference_out_of_catalog")))
    for member_id in _strings(data.get("reference_member_ids")):
        (references if member_id in members_by_id else outside).append(member_id)
    gender = data.get("gender")
    return Preference(
        is_appearance=bool(data.get("is_appearance")),
        gender=gender if gender in GENDERS else None,
        traits=tuple(traits),
        reference_member_ids=tuple(references),
        reference_out_of_catalog=tuple(outside),
        exclude_artists=tuple(
            artists[name.casefold()]
            for name in _strings(data.get("exclude_artists"))
            if name.casefold() in artists
        ),
        non_trait_constraints=tuple([*_strings(data.get("non_trait_constraints")), *unmapped]),
    )


def from_json(data: dict) -> Preference:
    """讀回快取裡已驗證過的偏好。"""

    return Preference(
        is_appearance=bool(data["is_appearance"]),
        gender=data["gender"],
        traits=tuple(Trait(**t) for t in data["traits"]),
        reference_member_ids=tuple(data["reference_member_ids"]),
        reference_out_of_catalog=tuple(data["reference_out_of_catalog"]),
        exclude_artists=tuple(data["exclude_artists"]),
        non_trait_constraints=tuple(data["non_trait_constraints"]),
    )


def adjust_scores(
    scores: dict[str, float],
    preference: Preference,
    members_by_tag: dict[str, frozenset[str]],
    *,
    bonus: float = TRAIT_BONUS,
    penalty: float = TRAIT_PENALTY,
) -> dict[str, float]:
    """標準化後的 v4 分數加上特質分：符合正向特質加分，符合否定特質扣分（不刪除）。"""

    adjusted = dict(scores)
    for trait in preference.traits:
        step = (bonus if trait.polarity == "+" else -penalty) * WEIGHTS[trait.weight]
        for member_id in members_by_tag.get(trait.tag, ()):
            if member_id in adjusted:
                adjusted[member_id] += step
    return adjusted


def filter_ranked(
    ranked: list[str], preference: Preference, members_by_id: dict[str, dict[str, str]]
) -> list[str]:
    """排除指定的團和參照成員本人；性別不合的往後排。"""

    excluded = set(preference.exclude_artists)
    references = set(preference.reference_member_ids)
    kept = [
        i
        for i in ranked
        if i not in references and members_by_id.get(i, {}).get("artist") not in excluded
    ]
    if not preference.gender:
        return kept
    matches = [i for i in kept if members_by_id[i].get("gender_group") == preference.gender]
    return matches + [i for i in kept if i not in set(matches)]


@dataclass
class PreferenceCache:
    path: Path
    model: str
    entries: dict[str, dict] = field(default_factory=dict)
    # 讀舊版提示詞的結果時指定（例如重現 test3 的 pref-v3）。
    prompt_version: str = PROMPT_VERSION

    @classmethod
    def load(cls, path: Path, model: str, prompt_version: str = PROMPT_VERSION) -> PreferenceCache:
        cache = cls(path, model, prompt_version=prompt_version)
        if path.exists():
            stored = json.loads(path.read_text(encoding="utf-8"))
            cache.entries = stored.get("entries", {})
        return cache

    def key(self, query: str) -> str:
        # 提示詞版本和模型都算進 key：換了任一個都不能拿到別的版本的解析結果。
        payload = f"{self.prompt_version}\n{self.model}\n{query}"
        return hashlib.sha256(payload.encode()).hexdigest()

    def get(self, query: str) -> Preference | None:
        entry = self.entries.get(self.key(query))
        return from_json(entry["preference"]) if entry else None

    def put(self, query: str, preference: Preference) -> None:
        self.entries[self.key(query)] = {
            "prompt_version": self.prompt_version,
            "model": self.model,
            "preference": preference.to_json(),
        }

    def save(self) -> None:
        # 舊版提示詞的結果也留著，test3 要用 pref-v3 的結果重現。
        payload = {"entries": self.entries}
        self.path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8"
        )

    def digest(self) -> str:
        return hashlib.sha256(self.path.read_bytes()).hexdigest()


class PreferenceParser:
    """問句 → 偏好。先查快取；live=False 時快取沒有就不解析（評估用）。

    提示詞不附成員表（pref-v5 起；pref-v6 只把範例換成自己寫的句子，不再用粉絲貼文）：Gemini 只判斷特質、否定、程度、性別、是不是長相題，並照原文
    列出提到的人名、團名和是不是負向參照；本機再用別名表整個名字精確比對。對不上、團名不符、
    同名分不清或目錄外的人一律不算參照成員（pref-v4 在問句裡找子字串，韓文常把「한」「진」
    這類字誤認成成員）。
    """

    def __init__(
        self,
        llm,
        tags: list[TraitTag],
        members: list[dict[str, str]],
        names: CuratorQueryParser | None = None,
        cache: PreferenceCache | None = None,
        *,
        live: bool = True,
    ) -> None:
        self.llm = llm
        self.tags = tags
        self.members_by_id = {m["id"]: m for m in members}
        self.names = names
        self.cache = cache
        self.live = live

    def parse(self, query: str) -> Preference | None:
        if self.cache and (cached := self.cache.get(query)):
            return cached
        if not self.live or not self.llm or not self.llm.enabled:
            return None
        prompt = self.prompt(query)
        started = time.monotonic()
        try:
            text = self.llm.generate(
                prompt,
                temperature=0.0,
                max_output_tokens=400,
                response_mime_type="application/json",
            )
            data = json.loads(text)
            # 模型偶爾把物件包在陣列裡。
            if isinstance(data, list) and data and isinstance(data[0], dict):
                data = data[0]
            preference = validate(data, self.tags, self.members_by_id)
        except Exception:
            logger.exception(
                "Preference parsing failed after %.1fs (prompt %d chars); ranking with v4 only.",
                time.monotonic() - started,
                len(prompt),
            )
            return None
        logger.info(
            "Preference parsed in %.1fs (prompt %d chars).", time.monotonic() - started, len(prompt)
        )
        references, outside, negative = self.resolve_people(data.get("people"))
        preference = replace(
            preference,
            reference_member_ids=references,
            reference_out_of_catalog=outside,
            non_trait_constraints=(*preference.non_trait_constraints, *negative),
        )
        if self.cache:
            self.cache.put(query, preference)
        return preference

    def resolve_people(self, people) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
        """Gemini 列出的人名 → (參照成員, 對不上或分不清的原文, 負向參照)。"""

        references, outside, negative = [], [], []
        for person in people if isinstance(people, list) else []:
            if not isinstance(person, dict) or not str(person.get("name", "")).strip():
                continue
            name = str(person["name"]).strip()
            if person.get("negative") is True:
                negative.append(f"negative_reference: {name}")
                continue
            group = person.get("group") if isinstance(person.get("group"), str) else None
            ids = self.names.lookup_member(name, group) if self.names else frozenset()
            if len(ids) == 1:
                references.append(next(iter(ids)))
            else:
                outside.append(f"{name}（{group}）" if group else name)
        return (
            tuple(dict.fromkeys(references)),
            tuple(dict.fromkeys(outside)),
            tuple(dict.fromkeys(negative)),
        )

    def prompt(self, query: str) -> str:
        tags = "\n".join(
            f"- {t.tag}（{'長相' if 'appearance' in t.facets else '個性／聲音／舞台'}）：{t.label}"
            for t in self.tags
        )
        return PROMPT_TEMPLATE.format(tags=tags, examples=FEW_SHOT, query=query)


def _strings(value) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(v).strip() for v in value if str(v).strip()]


PROMPT_TEMPLATE = """你是 K-pop 推坑助理的偏好解析器。把粉絲的一句話（韓文、中文或英文）解析成 JSON，只輸出 JSON。人名只要照原文列出。

欄位：
- is_appearance：是否在問長相、外貌、臉型、某種「相」或顏值（只問個性、歌聲、舞蹈時是 false）
- gender：想找女偶像 "female"、男偶像 "male"（여돌／걸그룹／女團／girl group 是 female；남돌／보이그룹／男團／boy group 是 male）；沒有明說時，如果提到的人都是同一性別就用那個性別，否則 null
- traits：粉絲想要或不想要的特質，每個是 {{"tag", "raw", "polarity", "weight"}}
  - tag 只能從下面的特質表選；表裡沒有的說法不要放進 traits，改寫成 non_trait_constraints 的英文短語
  - 只有意思相同才對應，不要找「差不多」的特質硬套：
    - 描述臉、長相、「…상」「…相」的詞只能對應標「長相」的特質
    - 不同動物相不能互相代替（너구리상、곰상、펭귄상、햄스터상都不是 puppy_face 或 cat_face）
    - cute_personality 只用在明說個性、性格、愛撒嬌（애교、성격）；「귀여운」「可愛」「cute」「babygirl」說的是外表時，表裡沒有對應
    - cold_chic 只對應清冷、冷淡、高冷、냉미남／냉미녀、차도남／차도녀；날티、分위기、氣質、帥氣不是 cold_chic
  - raw：原文裡對應的詞
  - polarity："+" 想要；"-" 不想要（不要、別、말고、별로、not too、…以外、不是我的菜）
  - weight："high"（超、最、真的、ㄹㅇ、개、엄청、진짜、very、most、一定要），"low"（有點、약간、살짝、좀、a bit），其他 "mid"
- non_trait_constraints：其他條件的英文短語，例如 group_size<=6、rookie、not_too_famous、tall
- people：粉絲提到的偶像，每個是 {{"name", "group", "negative"}}
  - name：原文寫的名字，去掉님、씨、桑、醬這類稱呼，不要翻譯或改寫成別的語言
  - group：原文有寫團名才填（照原文），沒寫就 null；不要自己猜他是哪一團
  - negative：粉絲說不喜歡、不是他的菜、不要像他時是 true，其他 false

特質表：
{tags}

範例：
{examples}

粉絲的話：{query}
"""

FEW_SHOT = """粉絲的話：윈터처럼 차도녀 느낌 나는 여돌 있을까요? 여우상이면 더 좋고, 해원 같은 귀여운 이미지는 제 취향 아니에요
{"is_appearance": true, "gender": "female", "traits": [{"tag": "cold_chic", "raw": "차도녀", "polarity": "+", "weight": "mid"}, {"tag": "fox_face", "raw": "여우상", "polarity": "+", "weight": "mid"}], "non_trait_constraints": ["not_cute_image"], "people": [{"name": "윈터", "group": null, "negative": false}, {"name": "해원", "group": null, "negative": true}]}

粉絲的話：想找有點清冷、但不要太像兔子的女團成員，BLACKPINK 以外
{"is_appearance": true, "gender": "female", "traits": [{"tag": "cold_chic", "raw": "清冷", "polarity": "+", "weight": "low"}, {"tag": "rabbit_face", "raw": "像兔子", "polarity": "-", "weight": "mid"}], "non_trait_constraints": [], "people": []}

粉絲的話：any boy group members with a really deep voice? not looking for main dancers
{"is_appearance": false, "gender": "male", "traits": [{"tag": "low_voice", "raw": "really deep voice", "polarity": "+", "weight": "high"}, {"tag": "main_dancer", "raw": "main dancers", "polarity": "-", "weight": "mid"}], "non_trait_constraints": [], "people": []}

粉絲的話：喜歡安兪真那種清純感，WINNER 宋旻浩那樣的男生也可以，張元英不是我的菜
{"is_appearance": true, "gender": null, "traits": [{"tag": "innocent_pure", "raw": "清純感", "polarity": "+", "weight": "mid"}], "non_trait_constraints": [], "people": [{"name": "安兪真", "group": null, "negative": false}, {"name": "宋旻浩", "group": "WINNER", "negative": false}, {"name": "張元英", "group": null, "negative": true}]}
"""
