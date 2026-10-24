"""Generate synthetic fan queries per member to fine-tune the AI 入坑 encoder (v3).

Real fan requests are too few to train on (docs/semantic_curator/PLAN.md), so an LLM
writes queries a fan might send when looking for each member, conditioned on that
member's retrieval document and styled after real requests. Only real requests whose
recommendations all fall outside the bot's catalog serve as style examples: those never
appear in the real-dev / real-test sets, and the Codex test set is never shown at all.

Queries naming the member or their group are dropped so the encoder cannot learn to
match names alone.

The LLM is any OpenAI-compatible chat endpoint; by default a local MLX server:

    uvx --from mlx-lm mlx_lm.server --model mlx-community/Qwen3-4B-Instruct-2507-4bit \\
        --port 8089
    uv run --group curator python scripts/generate_synthetic_queries.py   # resumable
    uv run --group curator python scripts/generate_synthetic_queries.py --limit 3 --dry-run
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import re
import sys
import time
from functools import cache
from pathlib import Path

import requests

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.evaluate_curator import REAL_REQUEST_CSVS, _real_request_query
from src.bot.catalog import PlayZoneCatalog
from src.bot.semantic_index import _compact, load_member_documents

OUTPUT_CSV = PROJECT_ROOT / "data" / "curator" / "synthetic_queries.csv"
FIELDNAMES = ["member_id", "query", "generator"]
DEFAULT_BASE_URL = "http://127.0.0.1:8089/v1"
DEFAULT_MODEL = "mlx-community/Qwen3-4B-Instruct-2507-4bit"
QUERIES_PER_MEMBER = 15
STYLE_EXAMPLES_PER_PROMPT = 6
MIN_QUERY_CHARS = 8
MAX_QUERY_CHARS = 60
MAX_ATTEMPTS = 3


def main() -> None:
    args = _parse_args()
    members = PlayZoneCatalog(PROJECT_ROOT).load_bias_radar_members()
    documents = load_member_documents(PROJECT_ROOT, members)
    style_examples = load_style_examples(members)
    print(f"{len(style_examples)} style examples from out-of-catalog real requests")

    existing = [] if args.force else _read_existing()
    done = {row["member_id"] for row in existing}
    targets = [m for m in members if m["id"] in documents and m["id"] not in done]
    if args.limit is not None:
        targets = targets[: args.limit]
    rng = random.Random(args.seed)
    rows = list(existing)
    for index, member in enumerate(targets, start=1):
        examples = rng.sample(style_examples, STYLE_EXAMPLES_PER_PROMPT)
        prompt = build_prompt(documents[member["id"]], member, examples)
        queries = _generate_queries(args, prompt, member)
        print(f"{index}/{len(targets)} {member['artist']} {member['member']}: {len(queries)}")
        for query in queries[:3]:
            print(f"    {query}")
        rows.extend(
            {"member_id": member["id"], "query": query, "generator": args.model}
            for query in queries
        )
        if not args.dry_run:
            _write_rows(rows)
    print(f"\n{len(rows)} queries for {len({r['member_id'] for r in rows})} members")


def load_style_examples(members: list[dict[str, str]]) -> list[str]:
    rows = []
    for path in REAL_REQUEST_CSVS:
        with path.open(encoding="utf-8", newline="") as file:
            rows.extend(csv.DictReader(file))
    return [row["request"] for row in rows if _real_request_query(row, members) is None]


def build_prompt(document: str, member: dict[str, str], examples: list[str]) -> str:
    gender = "女團" if member.get("gender_group") == "female" else "男團"
    example_lines = "\n".join(f"- {example}" for example in examples)
    return f"""你在幫 K-pop 推薦系統製作訓練資料。請想像 {QUERIES_PER_MEMBER} 位不同的粉絲，
他們心中想找的偶像正好符合下方這位成員，但他們不知道這位成員是誰，所以只會描述自己的喜好。

規則：
- 使用繁體中文（台灣用語），口語、像在 LINE 上打字，長短不一（8 到 50 字）。
- 絕對不要出現這位成員的名字、暱稱或所屬團體名稱。
- 每句只依據下方資料裡的特質，不要捏造資料沒有的事。
- 角度要分散：外型與氣質、定位與實力、音色或舞蹈風格、綜藝與個性、
  拿「風格相近」的其他藝人做比較、抽象的情境或氛圍。
- 大約一半的句子提到想找{gender}、男生或女生；少數句子可以帶一個排除條件（例如「不要太甜的」）。
- 只輸出 JSON 字串陣列，例如 ["...", "..."]，不要其他文字。

真實粉絲的說話方式（只參考語氣，不要照抄內容）：
{example_lines}

成員資料：
{document}"""


def _generate_queries(args: argparse.Namespace, prompt: str, member: dict[str, str]) -> list[str]:
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            response = requests.post(
                f"{args.base_url}/chat/completions",
                json={
                    "model": args.model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.9,
                    "max_tokens": 1200,
                },
                timeout=300,
            )
            response.raise_for_status()
            text = response.json()["choices"][0]["message"]["content"]
            queries = clean_queries(_parse_json_list(text), member)
            if queries:
                return queries[:QUERIES_PER_MEMBER]
            print("  ! no usable queries; retrying", flush=True)
        except Exception as error:  # noqa: BLE001 - keep going on per-member failures
            print(f"  ! failed ({error}); retrying", flush=True)
        time.sleep(2 * attempt)
    return []


@cache
def _to_taiwan():
    # The local model drifts into simplified characters and mainland wording.
    import opencc

    return opencc.OpenCC("s2twp")


def _taiwan_wording(text: str) -> str:
    # OpenCC's s2twp writes 舞臺 where fans type 舞台, and reads 一出 (一出手, 一出現)
    # as the measure word 一齣, which fans only use for a play or drama.
    return re.sub(r"齣(?![戲劇])", "出", text.replace("臺", "台"))


def clean_queries(candidates: list[str], member: dict[str, str]) -> list[str]:
    banned = {_compact(member["member"]), _compact(member["artist"])}
    cleaned: list[str] = []
    for candidate in candidates:
        query = _taiwan_wording(_to_taiwan().convert(" ".join(str(candidate).split())))
        compact = _compact(query)
        if not MIN_QUERY_CHARS <= len(query) <= MAX_QUERY_CHARS:
            continue
        if any(name and name in compact for name in banned):
            continue
        if compact not in {_compact(q) for q in cleaned}:
            cleaned.append(query)
    return cleaned


def _parse_json_list(text: str) -> list[str]:
    match = re.search(r"\[.*\]", text, re.DOTALL)
    if not match:
        return []
    try:
        values = json.loads(match.group(0))
    except ValueError:
        return []
    return [value for value in values if isinstance(value, str)] if isinstance(values, list) else []


def _read_existing() -> list[dict[str, str]]:
    if not OUTPUT_CSV.exists():
        return []
    with OUTPUT_CSV.open(encoding="utf-8", newline="") as file:
        return list(csv.DictReader(file))


def _write_rows(rows: list[dict[str, str]]) -> None:
    with OUTPUT_CSV.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=FIELDNAMES, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--limit", type=int, default=None, help="only N members")
    parser.add_argument("--seed", type=int, default=20261024)
    parser.add_argument("--force", action="store_true", help="regenerate every member")
    parser.add_argument("--dry-run", action="store_true", help="print without writing")
    return parser.parse_args()


if __name__ == "__main__":
    main()
