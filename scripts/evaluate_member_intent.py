"""用真實推坑串評估 AI 入坑的成員排序（v5 的尺）。

題目是粉絲在找「某種成員」的貼文（Grok 蒐集，scripts/split_member_intent_eval.py 分
dev／test），答案是其他粉絲在回覆裡推薦的目錄內成員。「像某人」題的那位參照成員
不算答案。

- strong：只看有 2 位以上回覆者推薦的成員，只算有這種答案的題目（主要指標）
- lenient：回覆裡推薦過的成員都算
- hit@k：前 k 名有任一答案；mrr：前 10 名內第一個答案的倒數名次

- looks：外貌子集（intent_type 是 appearance／similar_to_member，或 similar_aspect 是
  appearance／vibe／styling），和 test3 的資料字典同一個定義

Bot 一次推 3 位，hit@3 是主要數字。test 和 test2 封存，要加 --final 才會跑。test 已在
v5 第一輪用掉（v5 int8 沒有贏 v4）；test2 是 Grok 另外蒐集的 50 題（member_intent_eval_v2），
只跑一次。

v4 是原本的上線版本（v3 編碼器、沒有證據向量和照片）。v5 改了共用的排序程式，所以 v4
的逐題結果是用 v4 的程式（git 上 v5 之前的版本）跑出來存在 eval_results 裡，這裡用
--baseline v4 讀存檔比較。

Usage:
    uv run --group curator python scripts/evaluate_member_intent.py v5 v5-retrained --baseline v4
    uv run --group curator python scripts/evaluate_member_intent.py v5 --split test2 --final --baseline v4
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sys
from collections import defaultdict
from collections.abc import Callable
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.bot.catalog import PlayZoneCatalog
from src.bot.curator_query import CuratorQueryParser
from src.bot.member_evidence import load_member_evidence
from src.bot.photo_similarity import PhotoSimilarity
from src.bot.preference import (
    PREFERENCE_CACHE_PATH,
    PreferenceCache,
    PreferenceParser,
    load_aliases,
    load_trait_tags,
)
from src.bot.semantic_index import (
    ONNX_ENCODER_DIR,
    OnnxEncoder,
    SemanticMemberIndex,
    SemanticMemberRanker,
    load_evidence_texts,
    load_member_documents,
)

EVAL_DIR = PROJECT_ROOT / "data" / "curator" / "member_intent"
RESULTS_DIR = PROJECT_ROOT / "data" / "curator" / "eval_results" / "member_intent"
STRONG_RECOMMENDERS = 2
LOOKS_INTENTS = ("appearance", "similar_to_member")
LOOKS_ASPECTS = ("appearance", "vibe", "styling")
KS = (3, 10)
MRR_DEPTH = 10

Ranker = Callable[[str], list[str]]


def build_ranker(
    encoder,
    *,
    evidence: bool = True,
    photos: bool = True,
    looks_signals: bool = False,
    preferences: bool = False,
) -> Ranker:
    members = PlayZoneCatalog(PROJECT_ROOT).load_bias_radar_members()
    index = SemanticMemberIndex(
        encoder,
        load_member_documents(PROJECT_ROOT, members),
        evidence=load_evidence_texts(PROJECT_ROOT, members) if evidence else None,
    )
    ranker = SemanticMemberRanker(
        index,
        members,
        {},
        CuratorQueryParser.load(PROJECT_ROOT, members, visual_similarity=looks_signals),
        load_member_evidence(PROJECT_ROOT),
        PhotoSimilarity.load(PROJECT_ROOT) if photos else None,
        _cached_preferences(members) if preferences else None,
        looks_signals=looks_signals,
    )
    return ranker.rank_ids


def _cached_preferences(members) -> PreferenceParser:
    """只讀快取（scripts/parse_preferences.py 先填好），評分時不呼叫模型。"""

    cache = PreferenceCache.load(PROJECT_ROOT / PREFERENCE_CACHE_PATH, model="")
    return PreferenceParser(
        None,
        load_trait_tags(PROJECT_ROOT),
        members,
        load_aliases(PROJECT_ROOT),
        cache,
        live=False,
    )


def _v3() -> OnnxEncoder:
    return OnnxEncoder(PROJECT_ROOT / ONNX_ENCODER_DIR)


RANKERS: dict[str, Callable[[], Ranker]] = {
    # 目前的程式關掉 v5 訊號：應該和 v4 一樣（多了 v5 補的中文別名）。
    "v4-now": lambda: build_ranker(_v3(), evidence=False, photos=False),
    # v4 加上 LLM 偏好解析的特質分、否定降權和排除。
    "v4+pref": lambda: build_ranker(_v3(), evidence=False, photos=False, preferences=True),
    # v5（test2 沒有通過）：長相題加上證據、參照成員和照片。
    "v5": lambda: build_ranker(_v3(), looks_signals=True),
    # 重新訓練的編碼器（第一輪封存測試沒有贏 v4），同樣的長相規則，只供參考。
    "v5-retrained": lambda: build_ranker(
        OnnxEncoder(PROJECT_ROOT / "models" / "bge-m3-v5-int8"), looks_signals=True
    ),
}


def load_split(split: str) -> list[dict]:
    requests = _read_csv(EVAL_DIR / f"{split}_requests.csv")
    answers = defaultdict(dict)
    for row in _read_csv(EVAL_DIR / f"{split}_answers.csv"):
        answers[row["request_id"]][row["member_id"]] = int(row["recommender_count"] or 0)
    questions = []
    for row in requests:
        references = set(_split(row["reference_member_ids"]))
        gold = {m: n for m, n in answers[row["request_id"]].items() if m not in references}
        if gold:
            questions.append({**row, "gold": gold})
    return questions


def score(questions: list[dict], rankings: dict[str, list[str]]) -> dict:
    per_question = {}
    for q in questions:
        ranked = rankings[q["request_id"]]
        row = {}
        for level, threshold in (("strong", STRONG_RECOMMENDERS), ("lenient", 1)):
            gold = {m for m, n in q["gold"].items() if n >= threshold}
            if not gold:
                continue
            for k in KS:
                row[f"{level}_hit@{k}"] = float(any(m in gold for m in ranked[:k]))
            rank = next((i for i, m in enumerate(ranked[:MRR_DEPTH], 1) if m in gold), None)
            row[f"{level}_mrr"] = 1 / rank if rank else 0.0
        per_question[q["request_id"]] = row
    looks = [q["request_id"] for q in questions if is_looks(q)]
    return {
        "overall": _mean(per_question.values()),
        "looks": _mean(per_question[i] for i in looks),
        "by_intent": {
            intent: _mean(
                per_question[q["request_id"]] for q in questions if q["intent_type"] == intent
            )
            for intent in sorted({q["intent_type"] for q in questions})
        },
        "per_question": per_question,
    }


def is_looks(question: dict) -> bool:
    return (
        question["intent_type"] in LOOKS_INTENTS
        or question.get("similar_aspect", "") in LOOKS_ASPECTS
    )


def sign_test(a: dict, b: dict, metric: str, ids=None) -> tuple[int, int, float]:
    """b 比 a 好的題數、差的題數、雙尾 p 值；ids 限定題目。"""

    wins = losses = 0
    for qid, row in a["per_question"].items():
        if metric in row and (ids is None or qid in ids):
            diff = b["per_question"][qid][metric] - row[metric]
            wins += diff > 0
            losses += diff < 0
    n = wins + losses
    tail = sum(math.comb(n, i) for i in range(min(wins, losses) + 1)) / 2**n if n else 1.0
    return wins, losses, min(1.0, 2 * tail)


def main() -> None:
    args = _parse_args()
    if args.split != "dev" and not args.final:
        raise SystemExit(f"{args.split} 封存中；最後驗收才加 --final")
    questions = load_split(args.split)
    members = {m["id"]: m for m in PlayZoneCatalog(PROJECT_ROOT).load_bias_radar_members()}
    out_dir = RESULTS_DIR / args.split
    out_dir.mkdir(parents=True, exist_ok=True)
    n_strong = sum(any(n >= STRONG_RECOMMENDERS for n in q["gold"].values()) for q in questions)
    print(f"{args.split}: {len(questions)} 題（strong {n_strong} 題）")
    results = {}
    if args.baseline:
        path = out_dir / f"{args.baseline}_summary.json"
        results[args.baseline] = json.loads(path.read_text(encoding="utf-8"))
        _print(args.baseline + "（存檔）", results[args.baseline], show_intents=False)
    for name in args.rankers:
        ranker = RANKERS[name]()
        rankings = {q["request_id"]: ranker(q["query_zh"]) for q in questions}
        results[name] = score(questions, rankings)
        (out_dir / f"{name}_summary.json").write_text(
            json.dumps(results[name], ensure_ascii=False, indent=1), encoding="utf-8"
        )
        if args.split == "dev":
            _write_rankings(out_dir / f"{name}_rankings.csv", questions, rankings, members)
        _print(name, results[name], show_intents=args.split == "dev")
    if args.baseline:
        for name in args.rankers:
            base = args.baseline
            for metric in ("strong_hit@3", "strong_mrr", "lenient_hit@3"):
                wins, losses, p = sign_test(results[base], results[name], metric)
                print(f"{name} vs {base} {metric}: 贏 {wins} 輸 {losses}，符號檢定 p={p:.3f}")
            looks = {q["request_id"] for q in questions if is_looks(q)}
            wins, losses, p = sign_test(results[base], results[name], "lenient_hit@3", looks)
            print(f"{name} vs {base} 外貌子集 lenient_hit@3: 贏 {wins} 輸 {losses}，p={p:.3f}")


def _print(name: str, result: dict, *, show_intents: bool) -> None:
    def line(metrics: dict) -> str:
        return "  ".join(f"{k}={v:.3f}" for k, v in metrics.items() if k != "n")

    print(f"[{name}] {line(result['overall'])}")
    if "looks" in result:
        print(f"    外貌子集 n={result['looks']['n']:2d}  {line(result['looks'])}")
    if show_intents:
        for intent, metrics in result["by_intent"].items():
            print(f"    {intent:18s} n={metrics['n']:2d}  {line(metrics)}")


def _write_rankings(path: Path, questions: list[dict], rankings: dict, members: dict) -> None:
    def label(member_id: str) -> str:
        m = members[member_id]
        return f"{m['artist']} {m['member']}"

    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(["request_id", "intent_type", "query_zh", "gold", "top10"])
        for q in questions:
            ranked = rankings[q["request_id"]][:10]
            gold = "|".join(
                f"{label(m)}×{n}" for m, n in sorted(q["gold"].items(), key=lambda x: -x[1])
            )
            top = "|".join(("*" if m in q["gold"] else "") + label(m) for m in ranked)
            writer.writerow([q["request_id"], q["intent_type"], q["query_zh"], gold, top])


def _mean(rows) -> dict:
    sums: dict[str, list[float]] = defaultdict(list)
    count = 0
    for row in rows:
        count += 1
        for key, value in row.items():
            sums[key].append(value)
    return {"n": count, **{key: sum(v) / len(v) for key, v in sorted(sums.items())}}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("rankers", nargs="+", choices=list(RANKERS))
    parser.add_argument("--split", choices=("dev", "test", "test2", "test3"), default="dev")
    parser.add_argument("--final", action="store_true", help="允許跑封存的 test")
    parser.add_argument("--baseline", help="存檔的基準結果（例如 v4），逐題做符號檢定")
    return parser.parse_args()


def _split(value: str) -> list[str]:
    # v1_7 用 |，member_intent_eval_v2 用 ;。
    return [part.strip() for part in re.split(r"[|;]", value) if part.strip()]


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as file:
        return list(csv.DictReader(file))


if __name__ == "__main__":
    main()
