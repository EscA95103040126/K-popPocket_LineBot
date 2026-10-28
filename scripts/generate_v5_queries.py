"""產生 AI 入坑 v5 的訓練問句：每條有來源的成員特質，寫成粉絲找人的 LINE 訊息。

v3 的問句是從整篇成員描述寫的，描述裡有沒根據的形容，風格範例也混進找歌的請求。
v5 改成一條證據一批問句：問句只講這一項特質，不點名，也不加資料沒有的特質，
encoder 才學得到「這種說法對到這個人」。事件紀錄（主持過某節目）不是推坑特質，不收。

這支腳本只需要 requests 和 opencc，可以在任何有 OpenAI 相容端點的機器上跑，例如
裝了 Ollama 的 RTX 5080 電腦。兩個模型各跑一次，混合句型：

    uv run --with requests --with opencc python scripts/generate_v5_queries.py \\
        --base-url http://127.0.0.1:11434/v1 --model taide
    uv run --with requests --with opencc python scripts/generate_v5_queries.py \\
        --base-url http://127.0.0.1:11434/v1 --model gemma4

可中斷續跑：已產生的 (evidence_id, model) 會略過。先用 --limit 3 --dry-run 看品質。
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import time
import unicodedata
from functools import cache
from pathlib import Path

import requests

PROJECT_ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_CSV = PROJECT_ROOT / "data" / "curator" / "member_evidence.csv"
MEMBERS_CSV = PROJECT_ROOT / "data" / "play_zone" / "bias_radar_members.csv"
ALIASES_CSV = PROJECT_ROOT / "data" / "curator" / "grok_aliases.csv"
DEFAULT_OUTPUT = PROJECT_ROOT / "data" / "curator" / "staging" / "v5_queries.csv"
FIELDNAMES = ["member_id", "evidence_id", "facet", "query", "generator", "prompt_version"]
PROMPT_VERSION = "v5-evidence-3"
QUERIES_PER_CLAIM = 6
# 多要幾句：檢查會刪掉偏離證據的句子，留下的才夠 QUERIES_PER_CLAIM。
QUERIES_REQUESTED = 9
MAX_CLAIMS_PER_MEMBER = 4
MIN_QUERY_CHARS = 8
MAX_QUERY_CHARS = 60
MAX_ATTEMPTS = 3
TRAIT_PERSPECTIVES = {"fan_perception", "press", "other_person"}
FACET_HINTS = {
    "vibe": "個性或氣質",
    "variety": "綜藝感",
    "vocal": "歌聲或聲線",
    "performance": "舞台表現",
    "contrast": "反差",
    "offstage_public": "私下的樣子",
    "appearance": "長相或外型類型",
}
# 試跑時 TAIDE 不管提示詞怎麼寫，都會把「饒舌擔當」寫成「主唱感、舞台強、私下 chill」。
# 問句提到證據沒講的面向就刪掉：各面向的用詞只要出現在問句、卻沒出現在證據裡，就是自己加的。
ASPECT_CUES = {
    "offstage": ("私下", "私底下", "平常", "平時", "台下", "舞台下", "舞台外", "日常", "本人"),
    "performance": ("舞台", "台上", "跳舞", "舞蹈", "舞技", "表演", "直拍", "饒舌", "rap"),
    "vocal": ("主唱", "唱歌", "歌聲", "聲音", "嗓音", "高音", "唱功", "聲線", "音色", "vocal"),
    "variety": ("綜藝", "節目", "主持", "實境"),
    # 「綜藝裡很親切」不等於「很搞笑」，搞笑要證據自己講到才行。
    "humor": ("搞笑", "好笑", "幽默", "ㄎㄧㄤ", "ㄎ一ㄤ", "有梗", "諧星", "呆萌", "搞怪", "笑點"),
    "appearance": ("長相", "長得", "顏值", "外型", "外表", "五官", "臉"),
}
FACET_ASPECTS = {
    "offstage_public": "offstage",
    "performance": "performance",
    "vocal": "vocal",
    "variety": "variety",
    "appearance": "appearance",
}
# 提示詞要求直接對機器人說話，模型仍會寫成論壇發問。
FORUM_PHRASES = ("有沒有人知道", "有人知道", "求大家", "各位", "大家推薦")
# 證據原文帶保留（「意見分歧」）時，模型會把負評也寫進去；沒人想入坑「評價兩極」的人。
NEGATIVE_PHRASES = ("兩極", "分歧", "爭議", "評價不一", "沒那麼", "不太穩", "被嫌", "黑粉")


def main() -> None:
    args = _parse_args()
    members = {row["id"]: row for row in _read_csv(args.members)}
    claims = select_claims(_read_csv(args.evidence), members)
    banned = banned_names(members, _read_csv(args.aliases) if args.aliases.exists() else [])
    # 這個模型用舊版提示詞產生的問句一律重做，不和新版混在一起。
    existing = [
        row
        for row in _read_csv_if_exists(args.output)
        if row["generator"] != args.model
        or (row.get("prompt_version") == PROMPT_VERSION and not args.force)
    ]
    done = {(row["evidence_id"], row["generator"]) for row in existing}
    targets = [c for c in claims if (c["evidence_id"], args.model) not in done]
    if args.limit is not None:
        targets = targets[: args.limit]
    print(f"{len(claims)} trait claims; {len(targets)} to generate with {args.model}")

    rows = list(existing)
    for index, claim in enumerate(targets, start=1):
        member = members[claim["member_id"]]
        prompt = build_prompt(claim, member)
        cleaned = clean_queries(_generate(args, prompt), banned)
        queries = [q for q in cleaned if stays_on_trait(q, claim)][:QUERIES_PER_CLAIM]
        print(
            f"{index}/{len(targets)} {member['artist']} {member['member']} [{claim['facet']}]"
            f" kept {len(queries)}/{len(cleaned)}"
        )
        for query in queries[:2]:
            print(f"    {query}")
        rows.extend(
            {
                "member_id": claim["member_id"],
                "evidence_id": claim["evidence_id"],
                "facet": claim["facet"],
                "query": query,
                "generator": args.model,
                "prompt_version": PROMPT_VERSION,
            }
            for query in queries
        )
        if not args.dry_run:
            _write_rows(args.output, rows)
    print(f"\n{len(rows)} queries in {args.output}")


def select_claims(
    evidence: list[dict[str, str]], members: dict[str, dict[str, str]]
) -> list[dict[str, str]]:
    """推坑特質才收；每位成員最多取幾條，避免證據多的人主導訓練。"""

    by_member: dict[str, list[dict[str, str]]] = {}
    for row in evidence:
        if row["member_id"] in members and row.get("perspective") in TRAIT_PERSPECTIVES:
            by_member.setdefault(row["member_id"], []).append(row)
    selected = []
    for member_id in sorted(by_member):
        rows = sorted(by_member[member_id], key=lambda r: -int(r.get("source_count") or 1))
        selected.extend(rows[:MAX_CLAIMS_PER_MEMBER])
    return selected


def build_prompt(claim: dict[str, str], member: dict[str, str]) -> str:
    gender = "女生" if member.get("gender_group") == "female" else "男生"
    group = "女團" if member.get("gender_group") == "female" else "男團"
    facet = FACET_HINTS.get(claim["facet"], "特質")
    return f"""你在幫 K-pop「AI 入坑」機器人做訓練資料。這個機器人幫粉絲找到值得入坑的成員。

有一位{group}成員，粉絲或報導對他的{facet}是這樣說的：
「{claim["value"]}」

請寫 {QUERIES_REQUESTED} 句不同粉絲會傳給機器人的 LINE 訊息：他們想找有這種{facet}的成員，
但不知道是誰，所以只描述自己想要的樣子。

規則：
- 繁體中文、台灣用語，口語，像真的在打字，長短不一（8 到 50 字）。
- 每句都是直接傳給機器人、在找「人」，例如「有沒有…的成員」「想找…的{gender}」「推一個…的」。
  不要寫成在論壇問別人（「有沒有人知道」「求大家」），也不要問歌、專輯或團體。
- 只寫讓人想入坑的那一面。原文裡的爭議、負評、意見分歧、「但是…」的保留都不要寫進去。
- 只能用原文裡的特質，可以換成意思相同的說法，不能換成別的特質。
  原文沒提到的面向（例如原文只講饒舌，就不要提唱歌、私下、綜藝或長相）一律不要寫。
  原文講的是兩面反差，就照原文的兩面寫，不要自己換成其他兩面。
- 不要出現任何人名、暱稱、團名、歌名或節目名。
- 大約一半的句子提到想找{group}或{gender}，其他不提性別。
- 只輸出 JSON 物件，格式是 {{"queries": ["…", "…"]}}，不要其他文字。"""


def stays_on_trait(query: str, claim: dict[str, str]) -> bool:
    """問句只能提證據本身的面向；論壇式發問也不收。"""

    text = _compact(query).replace("臺", "台")
    if any(phrase in text for phrase in FORUM_PHRASES + NEGATIVE_PHRASES):
        return False
    value = _compact(claim["value"]).replace("臺", "台")
    allowed = {FACET_ASPECTS.get(claim["facet"])}
    allowed |= {aspect for aspect, cues in ASPECT_CUES.items() if any(c in value for c in cues)}
    return all(
        aspect in allowed or not any(cue in text for cue in cues)
        for aspect, cues in ASPECT_CUES.items()
    )


def banned_names(members: dict[str, dict[str, str]], aliases: list[dict[str, str]]) -> set[str]:
    """所有成員與團體的名字都不能出現，問句只能靠特質對到人。"""

    names = {_compact(m["member"]) for m in members.values()}
    names |= {_compact(m["artist"]) for m in members.values()}
    for row in aliases:
        names |= {_compact(alias) for alias in row.get("aliases", "").split("|")}
    # 太短的英文別名（V、IN、DO）會誤殺一般用字；中日韓名字兩個字以上才算。
    return {n for n in names if len(n) >= 3 or (len(n) == 2 and not n.isascii())}


def clean_queries(candidates: list[str], banned: set[str]) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        query = _taiwan_wording(_to_taiwan().convert(" ".join(str(candidate).split())))
        compact = _compact(query)
        if not MIN_QUERY_CHARS <= len(query) <= MAX_QUERY_CHARS:
            continue
        if re.search(r"[a-z0-9]", compact) and any(
            re.search(rf"(?<![a-z0-9]){re.escape(n)}(?![a-z0-9])", compact)
            for n in banned
            if n.isascii()
        ):
            continue
        if any(n in compact for n in banned if not n.isascii()):
            continue
        if compact not in seen:
            seen.add(compact)
            cleaned.append(query)
    return cleaned


def _generate(args: argparse.Namespace, prompt: str) -> list[str]:
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            response = requests.post(
                f"{args.base_url}/chat/completions",
                json={
                    "model": args.model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.8,
                    "max_tokens": 800,
                    # TAIDE 不加這個常常輸出說明文字而不是 JSON（試跑 3 條就重試 3 次）。
                    "response_format": {"type": "json_object"},
                },
                timeout=300,
            )
            response.raise_for_status()
            text = response.json()["choices"][0]["message"]["content"]
            if queries := _parse_queries(text):
                return queries
            print("  ! no JSON queries; retrying", flush=True)
        except Exception as error:  # noqa: BLE001 - keep going on per-claim failures
            print(f"  ! failed ({type(error).__name__}); retrying", flush=True)
        time.sleep(2 * attempt)
    return []


@cache
def _to_taiwan():
    import opencc

    return opencc.OpenCC("s2twp")


def _taiwan_wording(text: str) -> str:
    # 同 generate_synthetic_queries.py：s2twp 會把舞台寫成舞臺、把一出寫成一齣。
    return re.sub(r"齣(?![戲劇])", "出", text.replace("臺", "台"))


def _compact(text: str) -> str:
    return unicodedata.normalize("NFKC", text).casefold().replace(" ", "")


def _parse_queries(text: str) -> list[str]:
    """{"queries": [...]}，模型沒照做時也接受單純的字串陣列。"""

    match = re.search(r"\{.*\}|\[.*\]", text, re.DOTALL)
    if not match:
        return []
    try:
        values = json.loads(match.group(0))
    except ValueError:
        return []
    if isinstance(values, dict):
        values = values.get("queries")
    return [v for v in values if isinstance(v, str)] if isinstance(values, list) else []


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def _read_csv_if_exists(path: Path) -> list[dict[str, str]]:
    return _read_csv(path) if path.exists() else []


def _write_rows(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=FIELDNAMES, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:11434/v1")
    parser.add_argument("--model", required=True, help="Ollama 模型名稱，例如 taide、gemma4")
    parser.add_argument("--evidence", type=Path, default=EVIDENCE_CSV)
    parser.add_argument("--members", type=Path, default=MEMBERS_CSV)
    parser.add_argument("--aliases", type=Path, default=ALIASES_CSV)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--limit", type=int, default=None, help="只跑前 N 條證據")
    parser.add_argument("--force", action="store_true", help="重新產生這個模型的全部問句")
    parser.add_argument("--dry-run", action="store_true", help="只印出，不寫檔")
    return parser.parse_args()


if __name__ == "__main__":
    main()
