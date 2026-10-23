"""Score AI curator rankers against the curator query sets.

Each ranker turns a query into a ranked list of bias radar member ids. We report:

- artist_hit@k: any of the top-k members belongs to an expected artist (all queries)
- member_hit@k: any of the top-k members is an expected member (queries with expected_ids)
- artist_mrr: reciprocal rank of the first member from an expected artist, within the top 10

The bot shows three members, so k=3 is the headline number. v1 breaks score ties with
a shuffle, so every ranker is scored over several seeds and averaged.

Query sets (see docs/semantic_curator/PLAN.md for why they never overlap):

- codex: 60 queries Codex wrote without seeing any curator documents (main test set)
- real-dev: Grok's real fan requests from Reddit; only used to tune the group weight
- real-test: the other real fan requests with an answer inside the bot's catalog
- real-test-discovery: real-test minus requests whose every answer is an artist the
  query itself names ("more songs by ILLIT"); AI 入坑 helps people find *new* artists,
  so those are out of scope. The cut is mechanical so it cannot be tuned to a ranker.

Gemini responses are cached in data/curator/eval_results/llm_cache.json so reruns are
free and repeatable.

Usage:
    python scripts/evaluate_curator.py                          # every ranker on codex
    python scripts/evaluate_curator.py v1 v2-bge-m3+rules       # selected rankers
    python scripts/evaluate_curator.py --set real-dev v2-bge-m3+g0.5+rules
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
import sys
from collections.abc import Callable
from functools import cache
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.bot.catalog import PlayZoneCatalog
from src.bot.features.ai_curator import AiCuratorFeature, _prioritize_members_with_mv
from src.bot.llm import GeminiTextClient
from src.bot.semantic_index import (
    EMBEDDING_MODELS,
    ONNX_MODEL_KEY,
    SemanticMemberIndex,
    _compact,
    apply_query_rules,
    build_encoder,
    load_group_documents,
    load_member_documents,
    referenced_artists,
)
from src.bot.sessions import InMemorySessionStore
from src.config import settings

CURATOR_DIR = PROJECT_ROOT / "data" / "curator"
EVAL_QUERIES_CSV = CURATOR_DIR / "eval_queries.csv"
REAL_REQUEST_CSVS = (
    CURATOR_DIR / "grok_real_requests.csv",
    CURATOR_DIR / "grok_real_requests_more.csv",
)
RESULTS_DIR = CURATOR_DIR / "eval_results"
LLM_CACHE_JSON = RESULTS_DIR / "llm_cache.json"
QUERY_SETS = ("codex", "real-dev", "real-test", "real-test-discovery")
# Reddit rows were built from search snippets (pages would not open), so their labels
# are the least reliable; good enough to pick one weight, not to report results.
REAL_DEV_PLATFORMS = {"Reddit"}
GROUP_WEIGHT_GRID = (0.25, 0.5, 0.75, 1.0, 1.5)
SEEDS = (0, 1, 2, 3, 4)
KS = (3, 5)
MRR_DEPTH = 10

Ranker = Callable[[str], list[str]]


class CachedLLM:
    """GeminiTextClient stand-in that replays cached responses keyed by prompt."""

    def __init__(self, client: GeminiTextClient | None) -> None:
        self.client = client
        self.cache: dict[str, str] = (
            json.loads(LLM_CACHE_JSON.read_text(encoding="utf-8"))
            if LLM_CACHE_JSON.exists()
            else {}
        )

    @property
    def enabled(self) -> bool:
        return self.client is not None and self.client.enabled

    def generate(self, prompt: str, **kwargs) -> str:
        key = hashlib.sha256(json.dumps([prompt, kwargs], sort_keys=True).encode()).hexdigest()
        if key not in self.cache:
            if self.client is None:
                raise RuntimeError("LLM disabled")
            self.cache[key] = self.client.generate(prompt, **kwargs)
            RESULTS_DIR.mkdir(parents=True, exist_ok=True)
            LLM_CACHE_JSON.write_text(
                json.dumps(self.cache, ensure_ascii=False, indent=1), encoding="utf-8"
            )
        return self.cache[key]


def build_v1_ranker(seed: int, *, use_llm: bool) -> Ranker:
    catalog = PlayZoneCatalog(PROJECT_ROOT)
    client = (
        GeminiTextClient(settings.gemini_api_key, settings.gemini_model, timeout_seconds=30)
        if use_llm and not settings.use_gemini_mock
        else None
    )
    feature = AiCuratorFeature(
        catalog,
        CachedLLM(client),
        random.Random(seed),
        InMemorySessionStore(),
        is_fixed_command=lambda _message: False,
    )
    mv_artists = {
        row.get("artist", "").strip()
        for row in catalog.load_daily_kpop_rows("MV")
        if row.get("artist", "").strip()
    }

    def rank(query: str) -> list[str]:
        # Mirrors AiCuratorFeature._build_ai_curator_context's member ordering.
        profile = feature._resolve_ai_curator_profile(query)
        members = _prioritize_members_with_mv(
            feature._rank_bias_radar_members_for_curator(profile), mv_artists
        )
        return [member["id"] for member in members]

    return rank


@cache
def _semantic_index(model_key: str, include_enrichment: bool) -> SemanticMemberIndex:
    members = PlayZoneCatalog(PROJECT_ROOT).load_bias_radar_members()
    documents = load_member_documents(PROJECT_ROOT, members, include_enrichment=include_enrichment)
    return SemanticMemberIndex(
        build_encoder(model_key, PROJECT_ROOT),
        documents,
        group_documents=load_group_documents(PROJECT_ROOT),
        member_artists={member["id"]: member["artist"] for member in members},
    )


@cache
def build_v2_ranker(
    model_key: str,
    *,
    include_enrichment: bool,
    group_weight: float,
    rules: bool,
    exclude_referenced: bool = True,
) -> Ranker:
    # Embedding ranking is deterministic, so one ranker serves every seed.
    index = _semantic_index(model_key, include_enrichment)
    members_by_id = {
        row["id"]: row for row in PlayZoneCatalog(PROJECT_ROOT).load_bias_radar_members()
    }

    @cache
    def rank(query: str) -> list[str]:
        ranked = index.rank(query, group_weight)
        if not rules:
            return ranked
        return apply_query_rules(
            query, ranked, members_by_id, exclude_referenced=exclude_referenced
        )

    return rank


RANKERS: dict[str, Callable[[int], Ranker]] = {
    "v1-keyword": lambda seed: build_v1_ranker(seed, use_llm=False),
    "v1": lambda seed: build_v1_ranker(seed, use_llm=True),
}
for _model_key in [*EMBEDDING_MODELS, ONNX_MODEL_KEY]:
    # (suffix, Grok member enrichment, group weight, query rules)
    _variants = [
        ("-gemini-only", False, 0.0, False),
        ("", True, 0.0, False),
        ("+rules", True, 0.0, True),
    ] + [(f"+g{weight}+rules", True, weight, True) for weight in GROUP_WEIGHT_GRID]
    for _suffix, _enrich, _weight, _rules in _variants:
        RANKERS[f"v2-{_model_key}{_suffix}"] = (
            lambda seed, key=_model_key, e=_enrich, w=_weight, r=_rules: build_v2_ranker(
                key, include_enrichment=e, group_weight=w, rules=r
            )
        )
    # Gender filter only, without demoting artists the query names.
    RANKERS[f"v2-{_model_key}+gender"] = lambda seed, key=_model_key: build_v2_ranker(
        key, include_enrichment=True, group_weight=0.0, rules=True, exclude_referenced=False
    )


def main() -> None:
    args = _parse_args()
    members = PlayZoneCatalog(PROJECT_ROOT).load_bias_radar_members()
    member_artist = {row["id"]: row["artist"] for row in members}
    queries = load_query_set(args.set, members)
    results_dir = RESULTS_DIR if args.set == "codex" else RESULTS_DIR / args.set
    results_dir.mkdir(parents=True, exist_ok=True)
    print(f"Query set {args.set}: {len(queries)} queries")
    for name in args.rankers or RANKERS:
        summary = evaluate(name, queries, member_artist, results_dir)
        (results_dir / f"{name}_summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        _print_summary(name, summary)


def load_query_set(name: str, members: list[dict[str, str]]) -> list[dict[str, str]]:
    if name == "codex":
        return _read_csv(EVAL_QUERIES_CSV)
    rows = [row for path in REAL_REQUEST_CSVS for row in _read_csv(path)]
    wanted = [
        row for row in rows if (row.get("platform") in REAL_DEV_PLATFORMS) == (name == "real-dev")
    ]
    queries = [query for row in wanted if (query := _real_request_query(row, members))]
    if name == "real-test-discovery":
        queries = [query for query in queries if not _asks_for_named_artist(query, members)]
    return queries


def _asks_for_named_artist(query: dict[str, str], members: list[dict[str, str]]) -> bool:
    by_id = {member["id"]: member["artist"] for member in members}
    expected = set(_split(query["expected_artists"])) | {
        by_id[member_id] for member_id in _split(query["expected_ids"])
    }
    return expected <= referenced_artists(_compact(query["query"]), members)


def _real_request_query(row: dict[str, str], members: list[dict[str, str]]) -> dict | None:
    """Map a real request onto catalog ids; None when nothing it recommends is in the bot."""

    artists = {member["artist"] for member in members}
    member_ids = {
        (member["artist"].casefold(), member["member"].casefold()): member["id"]
        for member in members
    }
    expected_ids = []
    for recommended in _split(row.get("recommended_members", "")):
        for artist in artists:
            if recommended.casefold().startswith(artist.casefold() + " "):
                name = recommended[len(artist) + 1 :].strip().casefold()
                if member_id := member_ids.get((artist.casefold(), name)):
                    expected_ids.append(member_id)
    expected_artists = [
        artist for artist in _split(row.get("recommended_groups", "")) if artist in artists
    ]
    if not expected_ids and not expected_artists:
        return None
    return {
        "qid": row["req_id"],
        "query": row["request"],
        "expected_ids": "|".join(expected_ids),
        "expected_artists": "|".join(expected_artists),
        "type": row.get("request_type") or "其他",
    }


def evaluate(
    name: str,
    queries: list[dict[str, str]],
    member_artist: dict[str, str],
    results_dir: Path,
) -> dict:
    query_types = list(dict.fromkeys(query["type"] for query in queries))
    per_seed = []
    for seed in SEEDS:
        ranker = RANKERS[name](seed)
        rankings = {query["qid"]: ranker(query["query"]) for query in queries}
        if seed == SEEDS[0]:
            _write_rankings(name, queries, rankings, member_artist, results_dir)
        per_seed.append(_score(queries, rankings, member_artist, query_types))
    return {
        "ranker": name,
        "seeds": list(SEEDS),
        "overall": _mean_metrics([scores["overall"] for scores in per_seed]),
        "by_type": {
            query_type: _mean_metrics([scores["by_type"][query_type] for scores in per_seed])
            for query_type in query_types
        },
    }


def _score(
    queries: list[dict[str, str]],
    rankings: dict[str, list[str]],
    member_artist: dict[str, str],
    query_types: list[str],
) -> dict:
    rows = []
    for query in queries:
        ranked = rankings[query["qid"]]
        expected_ids = set(_split(query["expected_ids"]))
        expected_artists = set(_split(query["expected_artists"])) | {
            member_artist[member_id] for member_id in expected_ids
        }
        ranked_artists = [member_artist.get(member_id, "") for member_id in ranked]
        row = {"type": query["type"]}
        for k in KS:
            row[f"artist_hit@{k}"] = float(bool(set(ranked_artists[:k]) & expected_artists))
            if expected_ids:
                row[f"member_hit@{k}"] = float(bool(set(ranked[:k]) & expected_ids))
        first = next(
            (
                position
                for position, artist in enumerate(ranked_artists[:MRR_DEPTH], start=1)
                if artist in expected_artists
            ),
            None,
        )
        row["artist_mrr"] = 1 / first if first else 0.0
        rows.append(row)
    return {
        "overall": _average_rows(rows),
        "by_type": {
            query_type: _average_rows([row for row in rows if row["type"] == query_type])
            for query_type in query_types
        },
    }


def _average_rows(rows: list[dict]) -> dict[str, float]:
    metrics: dict[str, list[float]] = {}
    for row in rows:
        for key, value in row.items():
            if key != "type":
                metrics.setdefault(key, []).append(value)
    return {key: sum(values) / len(values) for key, values in metrics.items()} | {"n": len(rows)}


def _mean_metrics(runs: list[dict[str, float]]) -> dict[str, float]:
    keys = dict.fromkeys(key for run in runs for key in run)
    return {key: round(sum(run.get(key, 0.0) for run in runs) / len(runs), 4) for key in keys}


def _write_rankings(
    name: str,
    queries: list[dict[str, str]],
    rankings: dict[str, list[str]],
    member_artist: dict[str, str],
    results_dir: Path,
) -> None:
    with (results_dir / f"{name}_rankings.csv").open("w", encoding="utf-8", newline="") as file:
        writer = csv.writer(file, lineterminator="\n")
        writer.writerow(["qid", "type", "query", "expected", "top5"])
        for query in queries:
            top5 = rankings[query["qid"]][:5]
            writer.writerow(
                [
                    query["qid"],
                    query["type"],
                    query["query"],
                    query["expected_ids"] or query["expected_artists"],
                    "|".join(f"{member_artist.get(i, '?')}:{i}" for i in top5),
                ]
            )


def _print_summary(name: str, summary: dict) -> None:
    columns = ("artist_hit@3", "artist_hit@5", "member_hit@3", "member_hit@5", "artist_mrr")
    print(f"\n== {name} ==")
    print(f"{'':14}" + "".join(f"{column:>14}" for column in columns) + f"{'n':>6}")
    for label, metrics in [("overall", summary["overall"]), *summary["by_type"].items()]:
        cells = "".join(
            f"{metrics[column]:>14.3f}" if column in metrics else f"{'-':>14}" for column in columns
        )
        print(f"{label:14}{cells}{int(metrics['n']):>6}")


def _split(value: str) -> list[str]:
    return [part.strip() for part in value.split("|") if part.strip()]


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as file:
        return list(csv.DictReader(file))


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("rankers", nargs="*", choices=list(RANKERS), help="rankers to score")
    parser.add_argument("--set", choices=QUERY_SETS, default="codex", help="query set to score")
    return parser.parse_args()


if __name__ == "__main__":
    main()
