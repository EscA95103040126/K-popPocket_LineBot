"""從 Grok 成員證據批次產生 AI 入坑可用的證據表 data/curator/member_evidence.csv。

staging 原始批次含第三方貼文摘錄，不進 git；這裡只取出可以寫進推薦理由的主張：
verification_status=supported 且 usable_for_persona=yes。本人自述、單一來源、
pending／disputed 都不收。同一個 claim_id 在多批出現時以較新批次為準，
member_evidence_v1_11_clean 的同名檔覆蓋對應批次（帳號去識別與改判），
member_evidence_v1_13_staffname 再覆蓋在上面（非成員職員的真名改成「SM 職員」）。
appearance_v3 是 v5 的長相觀感（facet=appearance），規則相同；之後的長相批次只交
新增或改判的列，claim_id 加上 -v5、-v6 這類後綴，去掉後綴後同一條主張以最新一列為準
（改判成 superseded 的就不收）。

Usage:
    python scripts/build_member_evidence.py
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.bot.catalog import PlayZoneCatalog
from src.bot.member_evidence import EVIDENCE_FIELDS, MEMBER_EVIDENCE_PATH

STAGING_DIR = PROJECT_ROOT / "data/curator/staging/grok"
# 依交付順序，後面的覆蓋前面的。v1_11 只以 clean 覆蓋檔的形式交付，沒有自己的批次。
BATCHES = [
    *(f"member_evidence_v1_{n}/member_claims.csv" for n in (*range(1, 11), 12)),
    "appearance_v3/member_claims.csv",
    "appearance_claims_v4/member_claims_v4_additions.csv",
    # 排除 Naver Café 來源（robots.txt 禁止）後重新核對。
    "appearance_claims_v5_cafe_recheck/member_claims_v5_changes.csv",
    "appearance_claims_v6_source_recheck/member_claims_v6_changes.csv",
]
CLEAN_OVERLAY = "member_evidence_v1_11_clean"
STAFF_NAME_OVERLAY = "member_evidence_v1_13_staffname"
# 逐檔覆蓋，前面的優先：v1_13 > v1_11_clean > 原批次。
OVERLAYS = (STAFF_NAME_OVERLAY, CLEAN_OVERLAY)
VERSION_SUFFIX = re.compile(r"(-v\d+)+$")


def batch_file(staging: Path, batch: str) -> Path:
    for overlay in OVERLAYS:
        path = staging / overlay / batch.removeprefix("member_evidence_")
        if path.exists():
            return path
    return staging / batch


def collect(staging: Path, member_ids: set[str]) -> list[dict[str, str]]:
    latest: dict[str, dict[str, str]] = {}
    for batch in BATCHES:
        path = batch_file(staging, batch)
        if not path.exists():
            raise SystemExit(f"缺少 {path}")
        with path.open(encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                latest[VERSION_SUFFIX.sub("", row["claim_id"])] = row
    rows = []
    for row in latest.values():
        claim_id = row["claim_id"]
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
