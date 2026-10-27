"""AI 入坑 v4：別名消歧與保守的意圖約束，不新增成員事實。"""

from __future__ import annotations

import csv
import logging
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


def _normalize(text: str) -> str:
    return unicodedata.normalize("NFKC", text).casefold()


def alias_table_path(base_dir: Path) -> Path:
    path = base_dir / "data/curator/grok_aliases.csv"
    return path if path.exists() else base_dir / "data/curator/staging/grok/grok_aliases.csv"


@dataclass(frozen=True)
class EntityMention:
    start: int
    end: int
    kind: str
    candidates: tuple[str, ...]
    artist: str | None = None


@dataclass(frozen=True)
class CuratorQuery:
    mode: str
    facets: tuple[str, ...]
    entities: tuple[EntityMention, ...]
    search_query: str
    excluded_ids: frozenset[str]
    excluded_artists: frozenset[str]
    preferred_artists: frozenset[str]
    reference_artists: frozenset[str]


# 這些短字／常用字需要團名、明確偶像語境，或原文大寫才能作人名。
COMMON_ALIASES = {
    "v",
    "in",
    "do",
    "joy",
    "rose",
    "lily",
    "bae",
    "han",
    "ten",
    "san",
    "jun",
    "twice",
    "seventeen",
    "idle",
    "dream",
    "wish",
    "127",
    "meow",
    "highkey",
    "bp",
    "rv",
    "h2h",
    "kol",
    "十七",
}


class CuratorQueryParser:
    def __init__(self, members: list[dict[str, str]], alias_rows=()) -> None:
        self.members = {m["id"]: m for m in members}
        artists = {m["artist"] for m in members}
        self.names: dict[tuple[str, str], set[str]] = {}

        def add(kind: str, name: str, canonical: str) -> None:
            if name.strip():
                self.names.setdefault((kind, _normalize(name.strip())), set()).add(canonical)

        for m in members:
            add("member", m["member"], m["id"])
            add("group", m["artist"], m["artist"])
        for row in alias_rows:
            kind, canonical, group = (
                row.get(k, "").strip() for k in ("entity_type", "canonical", "group")
            )
            if kind == "member":
                if canonical not in self.members or self.members[canonical]["artist"] != group:
                    logger.warning("略過別名表中未知或團體不符的成員 ID：%s", canonical)
                    continue
                target = canonical
            elif kind in {"group", "subunit"} and group in artists:
                kind, target = "group", group
            else:
                logger.warning("略過別名表中未知的實體：%s", canonical)
                continue
            for name in row.get("aliases", "").split("|"):
                add(kind, name, target)

    @classmethod
    def load(cls, base_dir: Path, members: list[dict[str, str]]) -> CuratorQueryParser:
        path = alias_table_path(base_dir)
        try:
            with path.open(encoding="utf-8-sig", newline="") as f:
                reader = csv.DictReader(f)
                if not {"entity_type", "canonical", "group", "aliases"} <= set(
                    reader.fieldnames or ()
                ):
                    raise ValueError("別名表缺少必要欄位")
                return cls(members, list(reader))
        except (OSError, ValueError, csv.Error):
            logger.warning("無法讀取別名表，使用目錄中的標準名字。")
            return cls(members)

    def parse(self, query: str) -> CuratorQuery:
        text = _normalize(query)
        raw = unicodedata.normalize("NFKC", query)
        matches = []
        idol_context = any(
            cue in text for cue in ("偶像", "愛豆", "成員", "女團", "男團", "idol", "k-pop")
        )
        for (kind, alias), ids in self.names.items():
            pattern = re.escape(alias).replace(r"\ ", r"\s*")
            for match in re.finditer(rf"(?<![a-z0-9]){pattern}(?![a-z0-9])", text):
                if any(
                    text.rfind(left, 0, match.start()) > text.rfind(right, 0, match.start())
                    for left, right in (("〈", "〉"), ("《", "》"))
                ):
                    continue
                if alias == "txt" and match.start() and text[match.start() - 1] == ".":
                    continue
                if alias == "ive" and text[match.end() : match.end() + 1] in {"'", "’"}:
                    continue
                if (
                    alias in COMMON_ALIASES
                    and not idol_context
                    and not raw[match.start() : match.end()].isupper()
                ):
                    # 稍後允許同句團名為短名提供語境。
                    if not any(
                        _normalize(m["artist"]) in text
                        for i in ids
                        for m in [self.members.get(i, {})]
                        if m
                    ):
                        continue
                matches.append((match.start(), match.end(), kind, tuple(sorted(ids))))
        # 完整名字優先，避免 Kim Dahyun 又命中 Dahyun，或 HUENING KAI 又命中 KAI。
        accepted = []
        for item in sorted(matches, key=lambda x: (-(x[1] - x[0]), x[0], x[2])):
            if not any(item[0] < other[1] and other[0] < item[1] for other in accepted):
                accepted.append(item)
        groups = [(a, b, ids[0]) for a, b, kind, ids in accepted if kind == "group"]
        entities = []
        for start, end, kind, ids in sorted(accepted):
            if kind == "member" and len(ids) > 1:
                preceding = [(start - b, g) for a, b, g in groups if 0 <= start - b <= 20]
                following = [(a - end, g) for a, b, g in groups if 0 <= a - end <= 8]
                nearest = sorted(preceding or following)
                nearby = {g for distance, g in nearest if distance == nearest[0][0]}
                selected = tuple(i for i in ids if self.members[i]["artist"] in nearby)
                if len(selected) == 1:
                    ids = selected
            artist = (
                (self.members[ids[0]]["artist"] if kind == "member" else ids[0])
                if len(ids) == 1
                else None
            )
            entities.append(EntityMention(start, end, kind, ids, artist))

        resolved = [e for e in entities if e.artist is not None]
        refs = frozenset(e.artist for e in resolved)
        facets = tuple(
            name
            for name, cues in (
                ("vibe", ("氣質", "氛圍", "清冷", "高冷")),
                ("performance", ("舞台", "舞蹈", "跳舞", "表演", "dance")),
                ("vocal", ("聲線", "聲音", "唱腔", "嗓音", "vocal")),
            )
            if any(cue in text for cue in cues)
        )
        visual = any(cue in text for cue in ("長得像", "長相相似", "臉像", "外貌相似"))
        other = any(
            cue in text
            for cue in (
                "其他團",
                "別團",
                "別的團",
                "更多團",
                "新的團",
                "其他男團",
                "其他女團",
                "多認識",
                "多認識其他",
            )
        )
        similar = any(
            cue in text
            for cue in (
                "類似",
                "相似",
                "相近",
                "同類型",
                "很像",
                "像",
                "那種",
                "一樣",
                "那樣",
                "還適合",
                "還有誰",
                "推薦誰",
            )
        )
        same = any(cue in text for cue in ("同團", "他們的歌", "她們的歌", "這團的歌", "團內"))
        for e in resolved:
            prefix = text[max(0, e.start - 5) : e.start]
            suffix = text[e.end : e.end + 8]
            same = (
                same
                or prefix.endswith("入坑")
                or suffix.startswith("新粉")
                or bool(re.match(r"的?(?:歌|成員|舞台|直拍)", suffix))
                and not similar
                and not other
            )
        # 純作品參照不代表排除原團；歌曲層到位後再處理作品相似性。
        song_reference = "〈" in text or "《" in text
        mode = "general"
        if visual:
            mode = "unsupported_visual"
        elif refs:
            if same:
                mode = "same_artist"
            elif song_reference and not other and similar:
                mode = "related_music"
            elif similar or other:
                mode = "similarity"
        excluded_ids = set()
        excluded_artists = set()
        for e in resolved:
            # 否定只綁定緊鄰的實體，不能由不喜歡某首歌推成排除整團。
            prefix = text[max(0, e.start - 8) : e.start]
            suffix = text[e.end : e.end + 8]
            explicit_exclusion = bool(re.search(r"(?:不要|排除|不推薦|不想要)\s*$", prefix))
            except_entity = prefix.endswith("除了") and (
                suffix.startswith("之外") or suffix.startswith("以外")
            )
            if explicit_exclusion or except_entity:
                if e.kind == "member":
                    excluded_ids.update(e.candidates)
                else:
                    excluded_artists.add(e.artist)
            if (mode == "similarity" or (mode == "same_artist" and similar)) and e.kind == "member":
                excluded_ids.update(e.candidates)
            # 「像某團」常常原團就是好答案；只有明說其他團才硬排除。
            if mode == "similarity" and other:
                excluded_artists.add(e.artist)
        # 別名替換只改明確解析的人名；歧義不猜，也不改寫未知查詢。
        search = raw
        for e in reversed(entities):
            if e.artist is not None:
                name = self.members[e.candidates[0]]["member"] if e.kind == "member" else e.artist
                search = search[: e.start] + name + search[e.end :]
        preferred = refs - excluded_artists if mode == "same_artist" else frozenset()
        return CuratorQuery(
            mode,
            facets,
            tuple(entities),
            search,
            frozenset(excluded_ids),
            frozenset(excluded_artists),
            frozenset(preferred),
            refs,
        )

    def constrain(self, parsed: CuratorQuery, ranked: list[str]) -> list[str]:
        result = [
            i
            for i in ranked
            if i not in parsed.excluded_ids
            and self.members[i]["artist"] not in parsed.excluded_artists
        ]
        if parsed.preferred_artists:
            return sorted(
                result, key=lambda i: self.members[i]["artist"] not in parsed.preferred_artists
            )
        if parsed.mode == "similarity":
            # 參照團只保留排名最前的一位，其餘往後，讓前三名有其他團可認識。
            kept: list[str] = []
            later: list[str] = []
            for i in result:
                same = self.members[i]["artist"] in parsed.reference_artists
                if same and any(
                    self.members[k]["artist"] in parsed.reference_artists for k in kept
                ):
                    later.append(i)
                else:
                    kept.append(i)
            return kept + later
        return result
