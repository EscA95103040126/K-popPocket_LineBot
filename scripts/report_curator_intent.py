"""只用 real-dev 與獨立 demo，產出 v4 第一步的行為比較，不讀正式測試題。"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import random
import sys
from collections import Counter
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.evaluate_curator import load_query_set
from src.bot.catalog import PlayZoneCatalog
from src.bot.curator_query import CuratorQueryParser, alias_table_path
from src.bot.features.ai_curator import AiCuratorFeature
from src.bot.semantic_index import SemanticMemberRanker, _compact, referenced_artists
from src.bot.sessions import InMemorySessionStore

BASE = "v2-bge-m3-v3-int8+gender"
NEW = "v4-intent-aliases"
DEMOS = (
    "我喜歡 MEOVV 的 ANNA，有沒有相似類型的推薦？",
    "推薦那種不刻意搞笑，卻因為太認真反而很好笑的女偶像。",
    "想找平常很安靜，但一上舞台就像變了一個人的女愛豆。",
)


def read_rankings(name):
    path = ROOT / "data/curator/eval_results/real-dev" / f"{name}_rankings.csv"
    with path.open(encoding="utf-8") as f:
        return {
            r["qid"]: [x.split(":", 1)[1] for x in r["top5"].split("|")[:3] if x]
            for r in csv.DictReader(f)
        }


def main():
    catalog = PlayZoneCatalog(ROOT)
    members = catalog.load_bias_radar_members()
    artists = {m["id"]: m["artist"] for m in members}
    parser = CuratorQueryParser.load(ROOT, members)
    queries = load_query_set("real-dev", members)
    ranks = {name: read_rankings(name) for name in (BASE, NEW)}
    transitions = {key: Counter() for key in ("artist", "member")}
    structure = {name: Counter() for name in ranks}
    details = []
    for q in queries:
        expected_ids = set(q["expected_ids"].split("|")) - {""}
        expected_artists = (set(q["expected_artists"].split("|")) - {""}) | {
            artists[i] for i in expected_ids
        }
        named = referenced_artists(_compact(q["query"]), members)
        protected = expected_artists <= named
        hits = {}
        for name, ranked in ranks.items():
            top = ranked[q["qid"]]
            groups = [artists[i] for i in top]
            hits[name] = {
                "artist": bool(set(groups) & expected_artists),
                "member": bool(set(top) & expected_ids),
            }
            structure[name]["group_duplicate"] += len(set(groups)) < len(groups)
            structure[name]["all_same_group"] += len(set(groups)) == 1
            if protected:
                structure[name]["protected_n"] += 1
                structure[name]["protected_hits"] += hits[name]["artist"]
        for key in transitions:
            if key == "member" and not expected_ids:
                continue
            old, new = hits[BASE][key], hits[NEW][key]
            transitions[key]["win" if new > old else "loss" if new < old else "tie"] += 1
        parsed = parser.parse(q["query"])
        details.append(
            {
                "qid": q["qid"],
                "mode": parsed.mode,
                "facets": parsed.facets,
                "ambiguous": any(len(e.candidates) > 1 for e in parsed.entities),
                "excluded_ids": sorted(parsed.excluded_ids),
                "excluded_artists": sorted(parsed.excluded_artists),
                "hits": hits,
                "protected": protected,
            }
        )
    comparisons = {}
    for key, counts in transitions.items():
        wins, losses = counts["win"], counts["loss"]
        n = wins + losses
        p = (
            min(1.0, 2 * sum(math.comb(n, k) for k in range(min(wins, losses) + 1)) / 2**n)
            if n
            else 1.0
        )
        comparisons[key] = dict(counts) | {"two_sided_sign_p": p}
    runtime = SemanticMemberRanker.load(ROOT, members)
    if runtime is None:
        raise RuntimeError("無法載入 v3 模型，不能把 fallback 當成 v4 結果")
    baseline = SemanticMemberRanker(runtime.index, members, runtime.notes)
    demos = []
    for query in DEMOS:
        feature = AiCuratorFeature(
            catalog,
            None,
            random.Random(0),
            InMemorySessionStore(),
            lambda _: False,
            lambda: runtime,
        )
        context = feature._build_ai_curator_context(query)
        parsed = runtime.query_parser.parse(query)
        demos.append(
            {
                "query": query,
                "mode": parsed.mode,
                "facets": parsed.facets,
                "entities": [asdict(e) for e in parsed.entities],
                "v3_top3": [m["id"] for m in baseline.rank(query)[:3]],
                "v4_top3": [m["id"] for m in context["member_candidates"][:3]],
                "mv": context["daily_items"][0] if context["daily_items"] else None,
            }
        )
    paths = [
        ROOT / "src/bot/curator_query.py",
        ROOT / "src/bot/semantic_index.py",
        alias_table_path(ROOT),
    ]
    report = {
        "baseline": BASE,
        "ranker": NEW,
        "sha256": {
            str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths
        },
        "comparisons": comparisons,
        "structure": {k: dict(v) for k, v in structure.items()},
        "mode_counts": dict(Counter(d["mode"] for d in details)),
        "real_dev": details,
        "demos": demos,
    }
    path = ROOT / "docs/semantic_curator/v4_step1_diagnostics.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(
        json.dumps(
            {k: v for k, v in report.items() if k not in {"real_dev", "sha256"}},
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
