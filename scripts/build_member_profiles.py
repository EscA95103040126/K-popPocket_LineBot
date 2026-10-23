"""Write an open-vocabulary profile for every bias radar member using Gemini.

The semantic curator embeds these profiles instead of squeezing every query into the
fixed v1 tag vocabulary. Each profile is grounded on the member's existing tags plus
the kprofiles excerpt fetched from the row's source_url (shared with
label_member_persona.py), and Gemini is told not to invent concrete facts.

The run is resumable: rows already present in the output are skipped unless --force.

Usage:
    python scripts/build_member_profiles.py            # fill missing members
    python scripts/build_member_profiles.py --force     # regenerate every member
    python scripts/build_member_profiles.py --limit 5   # only the first N targets
    python scripts/build_member_profiles.py --dry-run   # print, do not write
    python scripts/build_member_profiles.py --apply-corrections  # redo Grok-flagged rows

Requires GEMINI_API_KEY in the environment / .env.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from pathlib import Path

import requests

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.label_member_persona import (
    MAX_API_ATTEMPTS,
    MEMBERS_CSV,
    REQUEST_PAUSE_SECONDS,
    RETRY_BASE_SECONDS,
    RETRYABLE_STATUS_CODES,
    _source_evidence_for_row,
)
from src.bot.llm import GeminiTextClient
from src.config import settings

PROFILES_CSV = PROJECT_ROOT / "data" / "curator" / "member_profiles.csv"
GROK_ENRICHMENT_CSV = PROJECT_ROOT / "data" / "curator" / "grok_enrichment.csv"
PROFILE_FIELDNAMES = ["id", "artist", "member", "gender_group", "profile", "keywords", "evidence"]
GEMINI_TIMEOUT_SECONDS = 40
MAX_KEYWORDS = 12


def main() -> None:
    args = _parse_args()
    if settings.use_gemini_mock:
        raise SystemExit("GEMINI_API_KEY is not set; cannot build member profiles.")

    members = _read_csv(MEMBERS_CSV)
    existing = {} if args.force else {row["id"]: row for row in _read_csv(PROFILES_CSV)}
    corrections = _load_corrections() if args.apply_corrections else {}
    targets = [row for row in members if row["id"] not in existing or row["id"] in corrections]
    if args.limit is not None:
        targets = targets[: args.limit]

    client = GeminiTextClient(
        settings.gemini_api_key, settings.gemini_model, timeout_seconds=GEMINI_TIMEOUT_SECONDS
    )
    print(f"Profiling {len(targets)} / {len(members)} members...", flush=True)
    failures = []
    for index, row in enumerate(targets, start=1):
        profile = _profile_member(client, row, corrections.get(row["id"], ""))
        label = f"{index}/{len(targets)} {row['artist']} {row['member']}"
        if profile is None:
            failures.append(row["id"])
            print(f"{label}: failed", flush=True)
        else:
            existing[row["id"]] = profile
            print(f"{label}: {profile['profile'][:40]}...", flush=True)
            if not args.dry_run:
                # Write after every member so a quota stop keeps the finished rows.
                _write_profiles(members, existing)
        time.sleep(REQUEST_PAUSE_SECONDS)

    print(f"\nDone. {len(existing)} / {len(members)} members have profiles.")
    if failures:
        print(f"Failed ({len(failures)}), rerun to retry: {', '.join(failures)}")


def _profile_member(
    client: GeminiTextClient, row: dict[str, str], correction: str = ""
) -> dict[str, str] | None:
    source_text = _source_evidence_for_row(row)
    prompt = _build_prompt(row, source_text, correction)
    for attempt in range(1, MAX_API_ATTEMPTS + 1):
        try:
            text = client.generate(
                prompt,
                temperature=0.3,
                max_output_tokens=600,
                response_mime_type="application/json",
            )
            parsed = _parse_profile(text)
            if parsed:
                return {
                    "id": row["id"],
                    "artist": row["artist"],
                    "member": row["member"],
                    "gender_group": row["gender_group"],
                    "evidence": "kprofiles" if source_text else "tags",
                    **parsed,
                }
            print("  ! unparseable response; retrying", flush=True)
        except requests.HTTPError as error:
            status = error.response.status_code if error.response is not None else None
            if status not in RETRYABLE_STATUS_CODES:
                print(f"  ! HTTP {status}; giving up on this member", flush=True)
                return None
            print(f"  ! HTTP {status}; retrying", flush=True)
        except Exception as error:  # noqa: BLE001 - keep going on per-row failures
            print(f"  ! failed ({error}); retrying", flush=True)
        if attempt < MAX_API_ATTEMPTS:
            time.sleep(RETRY_BASE_SECONDS * attempt)
    return None


def _build_prompt(row: dict[str, str], source_text: str, correction: str = "") -> str:
    source_block = source_text or "抓不到來源資料，請只依現有標籤撰寫，並避免任何具體事實。"
    correction_block = (
        f"\n上一版描述經查核有以下問題，這次必須修正，且以這段更正為準：\n{correction}\n"
        if correction
        else ""
    )
    return f"""你是 K-pop 推薦系統的資料編輯。請為下方成員寫一段給推薦系統比對用的描述，輸出 JSON。

規則：
- 使用繁體中文（台灣用語），不要使用簡體字或中國用語。
- profile：80 到 150 字，描述舞台風格、形象氣質、在團內的角色，以及什麼樣的粉絲會喜歡這位成員。
- keywords：5 到 12 個開放式關鍵字，可以是風格、氣質、粉絲常用形容詞，不限於現有標籤。
- 只寫來源摘錄或現有標籤能支持、或廣為人知的特質；不確定就不要寫。
- 不要編造具體事件、日期、獎項、數字或戀愛傳聞。
- 只輸出 JSON：{{"profile": "...", "keywords": ["...", "..."]}}
{correction_block}
成員資料：
- 團體：{row.get("artist", "")}
- 成員：{row.get("member", "")}
- 性別組：{row.get("gender_group", "")}
- 外型：{row.get("appearance", "")}
- 定位：{row.get("position", "")}
- 氣質：{row.get("vibe", "")}
- 關係感：{row.get("relationship", "")}
- 人設：{row.get("persona", "")}

來源摘錄（kprofiles，已清洗截斷）：
{source_block}"""


def _parse_profile(text: str) -> dict[str, str] | None:
    raw = _parse_json_object(text)
    if raw is None:
        return None
    profile = str(raw.get("profile") or "").strip()
    keywords = raw.get("keywords") or []
    if isinstance(keywords, str):
        keywords = keywords.split("|")
    cleaned_keywords = [
        str(keyword).strip().replace("|", "/") for keyword in keywords if str(keyword).strip()
    ]
    if not profile or not cleaned_keywords:
        return None
    return {
        "profile": " ".join(profile.split()),
        "keywords": "|".join(dict.fromkeys(cleaned_keywords[:MAX_KEYWORDS])),
    }


def _parse_json_object(text: str) -> dict | None:
    cleaned = text.strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end < start:
        return None
    try:
        raw = json.loads(cleaned[start : end + 1])
    except (ValueError, TypeError):
        return None
    return raw if isinstance(raw, dict) else None


def _load_corrections() -> dict[str, str]:
    """Grok's fact-check issues, keyed by member id, for profiles it did not mark ok."""
    return {
        row["id"]: row["issue"].strip()
        for row in _read_csv(GROK_ENRICHMENT_CSV)
        if row.get("verdict") in ("minor_issue", "wrong") and row.get("issue", "").strip()
    }


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as file:
        return list(csv.DictReader(file))


def _write_profiles(members: list[dict[str, str]], profiles: dict[str, dict[str, str]]) -> None:
    PROFILES_CSV.parent.mkdir(parents=True, exist_ok=True)
    rows = [profiles[member["id"]] for member in members if member["id"] in profiles]
    with PROFILES_CSV.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=PROFILE_FIELDNAMES, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="regenerate existing profiles")
    parser.add_argument("--limit", type=int, default=None, help="only process N target rows")
    parser.add_argument(
        "--apply-corrections",
        action="store_true",
        help="regenerate profiles Grok flagged in grok_enrichment.csv, with its fixes",
    )
    parser.add_argument("--dry-run", action="store_true", help="print without writing the file")
    return parser.parse_args()


if __name__ == "__main__":
    main()
