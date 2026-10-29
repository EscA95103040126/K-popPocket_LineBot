"""用 Gemini 解析偏好句，寫進快取 data/curator/llm_pref_cache.json。

評分（scripts/evaluate_member_intent.py v4+pref）只讀這份快取，不即時呼叫模型。快取以
提示詞版本加問句的雜湊為 key，已經有的不會重打。

--practice 也會用 Grok 的練習集（llm_pref_practice_v1，人工標了預期 JSON）比對解析結果：
性別、參照成員，以及對應到特質表的特質和正負向。

Usage:
    uv run python scripts/parse_preferences.py --practice --split dev test test2
    uv run python scripts/parse_preferences.py --split test3 --final   # 只在最後驗收
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.bot.catalog import PlayZoneCatalog
from src.bot.llm import GeminiTextClient
from src.bot.preference import (
    PREFERENCE_CACHE_PATH,
    PREFERENCE_MODEL,
    PROMPT_VERSION,
    PreferenceCache,
    PreferenceParser,
    load_aliases,
    load_trait_tags,
)
from src.config import Settings

PRACTICE_CSV = PROJECT_ROOT / "data/curator/staging/grok/llm_pref_practice_v1/practice_queries.csv"
EVAL_DIR = PROJECT_ROOT / "data/curator/member_intent"
# 範例用到 pp-0002 的句子，不算進準確度。
FEW_SHOT_IDS = {"pp-0002"}
# 練習集的特質名稱是 Grok 建議的，和特質表同義的對應過來，其他的本來就不該進 traits。
PRACTICE_TAGS = {
    "cat_face": "cat_face",
    "puppy_face": "puppy_face",
    "fox_face": "fox_face",
    "rabbit_face": "rabbit_face",
    "innocent_pure": "innocent_pure",
    "cold_look": "cold_chic",
    "cold_aloof": "cold_chic",
    "cold_city_man": "cold_chic",
    "chic": "cold_chic",
    "low_voice": "low_voice",
    "funny": "funny",
    "sunny_bright": "bright_cheerful",
    "main_dancer": "main_dancer",
    "main_rapper": "rapper",
    "leader": "reliable_leader",
}
# 免費額度每分鐘的請求數有限，慢慢打。
REQUEST_INTERVAL_SECONDS = 4.5


def main() -> None:
    args = _parse_args()
    if "test3" in args.split and not args.final:
        raise SystemExit("test3 封存中；最後驗收才加 --final")
    settings = Settings()
    llm = GeminiTextClient(settings.gemini_api_key, PREFERENCE_MODEL, timeout_seconds=30)
    if not llm.enabled:
        raise SystemExit("沒有設定 GEMINI_API_KEY")
    members = PlayZoneCatalog(PROJECT_ROOT).load_bias_radar_members()
    cache = PreferenceCache.load(PROJECT_ROOT / PREFERENCE_CACHE_PATH, PREFERENCE_MODEL)
    parser = PreferenceParser(
        llm, load_trait_tags(PROJECT_ROOT), members, load_aliases(PROJECT_ROOT), cache
    )
    queries = [q for split in args.split for q in _split_queries(split)]
    practice = _read_csv(PRACTICE_CSV) if args.practice else []
    queries += [row["query_text"] for row in practice]
    todo = [q for q in dict.fromkeys(queries) if cache.get(q) is None]
    print(f"{PROMPT_VERSION}：{len(queries)} 句，快取缺 {len(todo)} 句，模型 {PREFERENCE_MODEL}")
    failed = 0
    for i, query in enumerate(todo, 1):
        if parser.parse(query) is None:
            failed += 1
        if i % 10 == 0:
            cache.save()
            print(f"  {i}/{len(todo)}（失敗 {failed}）", flush=True)
        time.sleep(REQUEST_INTERVAL_SECONDS)
    cache.save()
    print(f"快取 {len(cache.entries)} 筆，失敗 {failed}，sha256={cache.digest()}")
    if practice:
        report_practice(practice, cache)


def report_practice(rows: list[dict[str, str]], cache: PreferenceCache) -> None:
    scored = [r for r in rows if r["practice_id"] not in FEW_SHOT_IDS]
    gender = refs = 0
    true_pos = false_pos = false_neg = 0
    for row in scored:
        got = cache.get(row["query_text"])
        if got is None:
            continue
        want = json.loads(row["expected_pref_json"])
        want_gender = want.get("gender") if want.get("gender") in ("female", "male") else None
        gender += got.gender == want_gender
        refs += set(got.reference_member_ids) == set(want.get("reference_member_ids") or [])
        expected = {
            (PRACTICE_TAGS[t["tag"]], t["polarity"])
            for t in want.get("traits") or []
            if t["tag"] in PRACTICE_TAGS
        }
        predicted = {(t.tag, t.polarity) for t in got.traits}
        true_pos += len(expected & predicted)
        false_pos += len(predicted - expected)
        false_neg += len(expected - predicted)
        if expected != predicted:
            print(f"  {row['practice_id']} 預期 {sorted(expected)} 解析 {sorted(predicted)}")
    n = len(scored)
    precision = true_pos / (true_pos + false_pos) if true_pos + false_pos else 0.0
    recall = true_pos / (true_pos + false_neg) if true_pos + false_neg else 0.0
    print(f"練習集 {n} 句：性別 {gender / n:.0%}、參照成員完全相同 {refs / n:.0%}")
    print(
        f"特質（含正負向）：precision {precision:.2f}、recall {recall:.2f}"
        f"（對 {true_pos}、多 {false_pos}、漏 {false_neg}）"
    )


def _split_queries(split: str) -> list[str]:
    return [row["query_zh"] for row in _read_csv(EVAL_DIR / f"{split}_requests.csv")]


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as file:
        return list(csv.DictReader(file))


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split", nargs="*", default=[], help="dev、test、test2、test3")
    parser.add_argument("--practice", action="store_true", help="一併解析並比對練習集")
    parser.add_argument("--final", action="store_true", help="允許解析封存的 test3")
    return parser.parse_args()


if __name__ == "__main__":
    main()
