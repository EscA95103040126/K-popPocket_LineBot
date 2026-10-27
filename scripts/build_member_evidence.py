"""從 Grok 成員證據批次產生 AI 入坑可用的證據表 data/curator/member_evidence.csv。

staging 原始批次含第三方貼文摘錄，不進 git；這裡只取出可以寫進推薦理由的主張：
verification_status=supported 且 usable_for_persona=yes。本人自述、單一來源、
pending／disputed 都不收。同一個 claim_id 在多批出現時以較新批次為準，
member_evidence_v1_11_clean 的同名檔覆蓋對應批次（帳號去識別與改判）。

Usage:
    python scripts/build_member_evidence.py
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.bot.catalog import PlayZoneCatalog
from src.bot.member_evidence import EVIDENCE_FIELDS, MEMBER_EVIDENCE_PATH

STAGING_DIR = PROJECT_ROOT / "data/curator/staging/grok"
BATCHES = [f"v1_{n}" for n in range(1, 11)]
CLEAN_OVERLAY = "member_evidence_v1_11_clean"


def batch_file(staging: Path, batch: str, name: str) -> Path:
    overlay = staging / CLEAN_OVERLAY / batch / name
    return overlay if overlay.exists() else staging / f"member_evidence_{batch}" / name


def collect(staging: Path, member_ids: set[str]) -> list[dict[str, str]]:
    latest: dict[str, dict[str, str]] = {}
    for batch in BATCHES:
        path = batch_file(staging, batch, "member_claims.csv")
        if not path.exists():
            raise SystemExit(f"缺少 {path}")
        with path.open(encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                latest[row["claim_id"]] = row
    rows = []
    for claim_id, row in latest.items():
        if row["verification_status"] != "supported" or row["usable_for_persona"] != "yes":
            continue
        if row["perspective"] == "self_view":
            continue
        if row["member_id"] not in member_ids:
            raise SystemExit(f"{claim_id} 的成員 ID 不在目錄裡：{row['member_id']}")
        rows.append(
            {
                "evidence_id": claim_id,
                "member_id": row["member_id"],
                "facet": row["facet"],
                "perspective": row["perspective"],
                "value": " ".join(row["value"].split()),
                "source_count": row.get("source_count") or "1",
            }
        )
    return sorted(rows, key=lambda r: (r["member_id"], r["facet"], r["evidence_id"]))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--staging", type=Path, default=STAGING_DIR)
    args = parser.parse_args()
    members = PlayZoneCatalog(PROJECT_ROOT).load_bias_radar_members()
    rows = collect(args.staging, {m["id"] for m in members})
    output = PROJECT_ROOT / MEMBER_EVIDENCE_PATH
    with output.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=EVIDENCE_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    covered = len({r["member_id"] for r in rows})
    print(f"Wrote {len(rows)} claims for {covered}/{len(members)} members to {output}")


if __name__ == "__main__":
    main()
