"""staging 品質關卡不把缺值、推論或有網址等同查證通過。"""

import csv

from scripts.validate_curator_staging import audit

MEMBERS = [{"id": "test-a", "artist": "TEST"}]


def write_rows(folder, name, rows):
    with (folder / name).open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def persona(**kwargs):
    row = dict(
        id="test-a",
        offstage="親切",
        onstage="insufficient_evidence",
        contrast="insufficient_evidence",
        variety_traits="",
        confidence="medium",
        sources="https://example.org/profile",
        evidence="親切:https://example.org/profile",
        source_tier="community_single",
        accessed_at="2026-10-25",
    )
    return row | kwargs


def test_inferred_contrast_and_unlisted_url_are_quarantined(tmp_path):
    write_rows(
        tmp_path,
        "grok_persona.csv",
        [
            persona(
                contrast="有些反差", evidence="反差:由兩項來源比較|親切:https://other.org/profile"
            )
        ],
    )
    report = audit(tmp_path, MEMBERS)
    codes = report["issue_counts"]
    assert codes["inferred_or_unlinked_evidence"] == 1
    assert codes["evidence_url_not_in_sources"] == 1
    assert report["status"] == "not_approved_for_runtime"
    assert report["approved_runtime_claims"] == 0


def test_missing_values_are_not_positive_evidence(tmp_path):
    write_rows(tmp_path, "grok_persona.csv", [persona()])
    report = audit(tmp_path, MEMBERS)
    assert report["files"]["grok_persona.csv"]["coverage"] == {
        "offstage": 1,
        "onstage": 0,
        "contrast": 0,
        "variety_traits": 0,
    }
    assert report["content_review"][0]["status"] == "pending_content_review"


def test_duplicate_and_unknown_member_fail_schema_check(tmp_path):
    write_rows(tmp_path, "grok_persona.csv", [persona(id="unknown"), persona(id="unknown")])
    counts = audit(tmp_path, MEMBERS)["issue_counts"]
    assert counts["unknown_member"] == 2
    assert counts["missing_or_duplicate_id"] == 1
    assert counts["missing_member_row"] == 1


def test_wiki_url_does_not_become_direct_press_source(tmp_path):
    write_rows(
        tmp_path,
        "grok_persona.csv",
        [
            persona(
                source_tier="press",
                sources="https://en.wikipedia.org/wiki/Test",
                evidence="親切:https://en.wikipedia.org/wiki/Test",
            )
        ],
    )
    assert audit(tmp_path, MEMBERS)["issue_counts"]["press_tier_without_direct_press_url"] == 1


def test_lexical_flags_are_review_requests_not_contradiction_verdicts(tmp_path):
    write_rows(tmp_path, "grok_persona.csv", [persona(offstage="外向")])
    report = audit(tmp_path, MEMBERS, [{"id": "test-a", "profile": "安靜而有反差"}])
    flags = report["profile_review_flags"][0]["flags"]
    assert "lexical_review:安靜/外向" in flags
    assert "existing_contrast_not_supported_by_staging_label" in flags
    assert report["approved_runtime_claims"] == 0


def test_invalid_access_date_and_confidence_are_rejected(tmp_path):
    write_rows(
        tmp_path, "grok_persona.csv", [persona(accessed_at="2026-02-30", confidence="very high")]
    )
    counts = audit(tmp_path, MEMBERS)["issue_counts"]
    assert counts["invalid_access_date"] == 1
    assert counts["invalid_confidence"] == 1


def test_malformed_csv_is_reported_without_crashing(tmp_path):
    write_rows(tmp_path, "grok_persona.csv", [persona()])
    with (tmp_path / "grok_persona.csv").open("a") as f:
        f.write("short,row\n")
    assert audit(tmp_path, MEMBERS)["issue_counts"]["malformed_csv_row"] == 1
