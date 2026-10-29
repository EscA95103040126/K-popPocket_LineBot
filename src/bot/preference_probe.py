"""量測部署環境裡偏好解析的實際延遲（預設不跑）。

設定環境變數 PREFERENCE_PROBE_RUNS=N 時，app 啟動後在背景執行緒用固定的 3 句問句打 N 次
偏好解析，再打 5 次只回一個字的短提示詞當網路基準；每次把提示詞字數和回應時間寫進 log，
最後寫中位數、p90 和最慢。只量時間、不改排序，也不碰使用者的請求。
"""

from __future__ import annotations

import logging
import os
import statistics
import threading
import time
from pathlib import Path

from src.bot.llm import GeminiTextClient
from src.bot.preference import PREFERENCE_MODEL, PROMPT_VERSION, PreferenceParser, load_trait_tags

logger = logging.getLogger(__name__)

PROBE_QUERIES = ("想找貓系長相的女偶像", "不要太可愛的男偶像，有沒有推薦", "想找舞台很有氣場的主唱")
BASELINE_RUNS = 5
# 等 app 起來再開始，兩次之間隔開，避免和使用者的請求搶免費額度。
START_DELAY_SECONDS = 30
INTERVAL_SECONDS = 5
TIMEOUT_SECONDS = 30


def start_preference_probe(api_key: str | None, base_dir: Path) -> threading.Thread | None:
    runs = int(os.getenv("PREFERENCE_PROBE_RUNS", "0") or 0)
    if runs <= 0 or not api_key:
        return None
    thread = threading.Thread(
        target=run_probe, args=(api_key, base_dir, runs), name="preference-probe", daemon=True
    )
    thread.start()
    return thread


def run_probe(api_key: str, base_dir: Path, runs: int, *, sleep=time.sleep) -> dict[str, list]:
    llm = GeminiTextClient(api_key, PREFERENCE_MODEL, timeout_seconds=TIMEOUT_SECONDS)
    parser = PreferenceParser(None, load_trait_tags(base_dir), [])
    sleep(START_DELAY_SECONDS)
    results: dict[str, list] = {"parse": [], "baseline": []}
    jobs = [("parse", parser.prompt(PROBE_QUERIES[i % len(PROBE_QUERIES)])) for i in range(runs)]
    jobs += [("baseline", "只回一個字：好")] * BASELINE_RUNS
    for i, (kind, prompt) in enumerate(jobs, 1):
        started = time.monotonic()
        try:
            llm.generate(
                prompt,
                temperature=0.0,
                max_output_tokens=400 if kind == "parse" else 10,
                response_mime_type="application/json" if kind == "parse" else None,
            )
            outcome = "ok"
        except Exception as error:
            outcome = type(error).__name__
        elapsed = time.monotonic() - started
        results[kind].append(elapsed)
        logger.warning(
            "PREF_PROBE %s %d/%d prompt=%s model=%s chars=%d elapsed=%.2fs %s",
            kind,
            i,
            len(jobs),
            PROMPT_VERSION,
            PREFERENCE_MODEL,
            len(prompt),
            elapsed,
            outcome,
        )
        sleep(INTERVAL_SECONDS)
    for kind, times in results.items():
        if times:
            logger.warning(
                "PREF_PROBE summary %s n=%d median=%.2fs p90=%.2fs max=%.2fs",
                kind,
                len(times),
                statistics.median(times),
                _percentile(times, 0.9),
                max(times),
            )
    return results


def _percentile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, round(q * (len(ordered) - 1))))]
