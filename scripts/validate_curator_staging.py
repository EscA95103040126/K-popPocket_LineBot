"""離線稽核 Grok staging；只檢查結構與證據指標，不把網址視為查證通過。"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from collections import Counter
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
REQUIRED = {
    "grok_songs.csv": {
        "song_id",
        "artist",
        "song",
        "release",
        "genre",
        "sound_features",
        "mood",
        "scenario",
        "vocal_traits",
        "similar_songs",
        "sources",
        "evidence",
        "source_tier",
        "accessed_at",
    },
    "grok_persona.csv": {
        "id",
        "offstage",
        "onstage",
        "contrast",
        "variety_traits",
        "confidence",
        "sources",
        "evidence",
        "source_tier",
        "accessed_at",
    },
    "grok_aliases.csv": {"entity_type", "canonical", "group", "aliases"},
    "idol_similarity_edges.csv": {
        "edge_id",
        "idol_a_id",
        "idol_b_id",
        "relation_type",
        "verification_status",
        "directionality",
        "source_url",
    },
    "idol_visual_profiles.csv": {"idol_id", "catalog_status", "feature_type", "source_url"},
    "fandom_semantic_lexicon.csv": {"term", "language", "intent_category", "source_url"},
}
SONG_FIELDS = ("genre", "sound_features", "mood", "scenario", "vocal_traits")
PERSONA_FIELDS = ("offstage", "onstage", "contrast", "variety_traits")
COMMUNITY_HOSTS = {"namu.moe", "namu.wiki", "kprofiles.com", "en.wikipedia.org"}


def present(value):
    return value.strip() not in {"", "insufficient_evidence"}


def read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        return set(reader.fieldnames or ()), list(reader)


def public_url(value):
    try:
        url = urlsplit(value)
        return url.scheme in {"http", "https"} and bool(url.hostname) and not url.username
    except ValueError:
        return False


def audit(directory, members, profiles=()):
    by_id = {m["id"]: m for m in members}
    artists = {m["artist"] for m in members}
    files, issues, content_review, pilot = {}, [], [], []

    def issue(file, key, code, **detail):
        issues.append({"file": file, "id": key, "code": code, **detail})

    persona = {}
    for name, required in REQUIRED.items():
        path = directory / name
        if not path.exists():
            issue(name, "", "missing_file")
            continue
        headers, rows = read_csv(path)
        missing = sorted(required - headers)
        files[name] = {
            "rows": len(rows),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "missing_columns": missing,
        }
        if missing:
            issue(name, "", "missing_columns", fields=missing)
            continue
        valid_rows = []
        for row_number, row in enumerate(rows, start=2):
            if None in row or any(v is None for v in row.values()):
                issue(name, str(row_number), "malformed_csv_row")
            else:
                valid_rows.append(row)
        rows = valid_rows
        key_field = {
            "grok_songs.csv": "song_id",
            "grok_persona.csv": "id",
            "idol_similarity_edges.csv": "edge_id",
        }.get(name)
        seen = set()
        for r in rows:
            key = (
                r.get(key_field, "")
                if key_field
                else r.get("canonical", r.get("idol_id", r.get("term", "")))
            )
            if None in r or any(v is None for v in r.values()):
                issue(name, key, "malformed_csv_row")
                continue
            if key_field:
                if not key or key in seen:
                    issue(name, key, "missing_or_duplicate_id")
                seen.add(key)
            if name == "grok_songs.csv" and r["artist"] not in artists:
                issue(name, key, "unknown_artist")
            if name == "grok_persona.csv" and key not in by_id:
                issue(name, key, "unknown_member")
            if name == "grok_songs.csv" and not re.fullmatch(
                r"\d{4}-(?:0[1-9]|1[0-2])", r["release"]
            ):
                issue(name, key, "invalid_release_month")
            if "accessed_at" in r:
                try:
                    date.fromisoformat(r["accessed_at"])
                except ValueError:
                    issue(name, key, "invalid_access_date")
            if "confidence" in r and r["confidence"] not in {"high", "medium", "low"}:
                issue(name, key, "invalid_confidence")
            if name == "grok_aliases.csv" and r["entity_type"] == "member":
                if r["canonical"] not in by_id or by_id[r["canonical"]]["artist"] != r["group"]:
                    issue(name, key, "alias_id_or_group_mismatch")
            if name == "idol_similarity_edges.csv":
                for column in ("idol_a_id", "idol_b_id"):
                    if r[column] not in by_id and not r[column].startswith("ooc-"):
                        issue(name, key, "unknown_edge_member", field=column)
            sources = [u for u in r.get("sources", r.get("source_url", "")).split("|") if u]
            for url in sources:
                if not public_url(url):
                    issue(name, key, "invalid_source_url", url=url)
            if name not in {"grok_songs.csv", "grok_persona.csv"}:
                continue
            evidence = [s for s in r["evidence"].split("|") if s]
            for segment in evidence:
                label, separator, rest = segment.partition(":http")
                if not separator:
                    issue(name, key, "inferred_or_unlinked_evidence", label=segment)
                    continue
                url = "http" + rest
                if not public_url(url) or url not in sources:
                    issue(name, key, "evidence_url_not_in_sources", label=label, url=url)
            if (
                r["source_tier"] == "press"
                and sources
                and all(urlsplit(u).hostname in COMMUNITY_HOSTS for u in sources)
            ):
                issue(name, key, "press_tier_without_direct_press_url")
            # 全部內容仍需人審；連結存在、可開啟、語意支持是三個不同狀態。
            content_review.append(
                {
                    "file": name,
                    "id": key,
                    "status": "pending_content_review",
                    "fields": [
                        f
                        for f in (SONG_FIELDS if name == "grok_songs.csv" else PERSONA_FIELDS)
                        if present(r[f])
                    ],
                }
            )
        if name in {"grok_songs.csv", "grok_persona.csv"}:
            fields = SONG_FIELDS if name == "grok_songs.csv" else PERSONA_FIELDS
            evidence = [s for r in rows for s in r["evidence"].split("|") if s]
            files[name].update(
                {
                    "coverage": {f: sum(present(r[f]) for r in rows) for f in fields},
                    "unique_urls": len({u for r in rows for u in r["sources"].split("|") if u}),
                    "evidence_items": len(evidence),
                    "evidence_items_with_url": sum(":http" in e for e in evidence),
                    "source_tiers": dict(Counter(r["source_tier"] for r in rows)),
                }
            )
        if name == "grok_persona.csv":
            persona = {r["id"]: r for r in rows}
            files[name]["contrast_labels"] = dict(Counter(r["contrast"] for r in rows))
            for member_id in by_id.keys() - persona.keys():
                issue(name, member_id, "missing_member_row")
        if name == "grok_songs.csv":
            files[name]["artist_counts"] = dict(Counter(r["artist"] for r in rows))
            files[name]["metadata_only"] = sum(
                not any(present(r[f]) for f in SONG_FIELDS) for r in rows
            )
            # 第一批每團三首；僅依原始順序和核心欄位完整性選待查核候選，完全不讀評估題。
            for artist in sorted(artists):
                options = [
                    r
                    for r in rows
                    if r["artist"] == artist
                    and present(r["genre"])
                    and present(r["sound_features"])
                ]
                chosen = options[:3]
                pilot.extend(
                    {
                        "song_id": r["song_id"],
                        "artist": artist,
                        "song": r["song"],
                        "status": "pending_content_review",
                    }
                    for r in chosen
                )
                if len(chosen) < 3:
                    issue(
                        name,
                        artist,
                        "pilot_core_coverage_shortfall",
                        available=len(chosen),
                        target=3,
                    )
    comparisons = []
    for profile in profiles:
        member_id = profile["id"]
        if member_id not in persona:
            continue
        r = persona[member_id]
        flags = []
        old = profile.get("profile", "")
        if "反差" in old and not present(r["contrast"]):
            flags.append("existing_contrast_not_supported_by_staging_label")
        # 這是全員的詞彙篩查，交給人審，不宣稱找到語意矛盾。
        for a, b in (("安靜", "外向"), ("安靜", "社交"), ("外向", "內向"), ("活潑", "安靜")):
            if a in old and b in r["offstage"]:
                flags.append(f"lexical_review:{a}/{b}")
        if flags:
            comparisons.append(
                {
                    "id": member_id,
                    "flags": flags,
                    "existing_profile": old,
                    "staging_offstage": r["offstage"],
                    "staging_onstage": r["onstage"],
                    "staging_contrast": r["contrast"],
                }
            )
    return {
        "status": "not_approved_for_runtime",
        "files": files,
        "issues": issues,
        "issue_counts": dict(Counter(i["code"] for i in issues)),
        "content_review": content_review,
        "pilot_candidates": pilot,
        "profile_review_flags": comparisons,
        "out_of_scope": ["長相相似", "造型相似"],
        "approved_runtime_claims": 0,
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input", type=Path, default=ROOT / "data/curator/staging/grok")
    p.add_argument("--output", type=Path, default=ROOT / "docs/semantic_curator/staging_audit.json")
    args = p.parse_args()
    _, members = read_csv(ROOT / "data/play_zone/bias_radar_members.csv")
    _, profiles = read_csv(ROOT / "data/curator/member_profiles.csv")
    report = audit(args.input, members, profiles)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(
        json.dumps(
            {
                "status": report["status"],
                "issue_counts": report["issue_counts"],
                "pilot_candidates": len(report["pilot_candidates"]),
                "profile_review_flags": len(report["profile_review_flags"]),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
