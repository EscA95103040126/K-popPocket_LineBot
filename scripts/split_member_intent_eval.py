"""把 Grok 的成員推坑評估集分成 dev／test。

dev 用來調 v5；test 封存，只在 v5 最後驗收一次。依 intent_type 和「有沒有 2 人以上
推薦的成員」分層，兩邊題型比例一致。test 寫出後只印題數和雜湊，不印內容。

Usage:
    uv run python scripts/split_member_intent_eval.py
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import random
from collections import defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = PROJECT_ROOT / "data" / "curator" / "staging" / "grok" / "member_intent_eval_v1_7"
OUTPUT_DIR = PROJECT_ROOT / "data" / "curator" / "member_intent"
SEED = 20261028


def main() -> None:
    args = _parse_args()
    source = Path(args.source)
    requests = _read_csv(source / "requests.csv")
    answers = _read_csv(source / "answers.csv")
    strong = {a["request_id"] for a in answers if int(a["recommender_count"] or 0) >= 2}

    strata: dict[tuple[str, bool], list[dict[str, str]]] = defaultdict(list)
    for row in requests:
        strata[(row["intent_type"], row["request_id"] in strong)].append(row)
    rng = random.Random(SEED)
    test_ids: set[str] = set()
    carry = 0
    for key in sorted(strata):
        rows = sorted(strata[key], key=lambda r: r["request_id"])
        rng.shuffle(rows)
        # 奇數層輪流把多出的一題給 dev／test，總數才不會偏一邊。
        n_test = (len(rows) + carry) // 2
        carry = (len(rows) + carry) % 2
        test_ids.update(r["request_id"] for r in rows[:n_test])

    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    for split, keep in (("dev", lambda i: i not in test_ids), ("test", test_ids.__contains__)):
        split_requests = [r for r in requests if keep(r["request_id"])]
        split_answers = [a for a in answers if keep(a["request_id"])]
        _write_csv(output / f"{split}_requests.csv", split_requests)
        _write_csv(output / f"{split}_answers.csv", split_answers)
        n_strong = sum(r["request_id"] in strong for r in split_requests)
        print(f"{split}: {len(split_requests)} 題，其中 {n_strong} 題有 2 人以上推薦")
    digest = hashlib.sha256()
    for name in ("test_requests.csv", "test_answers.csv"):
        digest.update((output / name).read_bytes())
    (output / "TEST_SEALED.txt").write_text(
        f"test 封存，v5 最後只驗收一次。\nsha256={digest.hexdigest()}\n", encoding="utf-8"
    )
    print(f"test sha256={digest.hexdigest()}")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default=str(SOURCE_DIR))
    parser.add_argument("--output", default=str(OUTPUT_DIR))
    return parser.parse_args()


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as file:
        return list(csv.DictReader(file))


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    main()
