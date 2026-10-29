"""證據表只收 supported 主張，挑選時以使用者問到的面向優先。"""

import csv

import pytest

from scripts.build_member_evidence import BATCHES, CLEAN_OVERLAY, collect
from src.bot.catalog import PlayZoneCatalog
from src.bot.member_evidence import load_member_evidence, pick_member_evidence, query_facets
from tests.fakes import REPO_ROOT

CLAIM_FIELDS = [
    "claim_id",
    "member_id",
    "facet",
    "value",
    "perspective",
    "verification_status",
    "usable_for_persona",
    "source_count",
]


def claim(claim_id, **overrides):
    row = {
        "claim_id": claim_id,
        "member_id": "twice-sana",
        "facet": "vibe",
        "value": "粉絲常說她親切",
        "perspective": "fan_perception",
        "verification_status": "supported",
        "usable_for_persona": "yes",
        "source_count": "3",
    }
    return row | overrides


def write_claims(folder, rows, name="member_claims.csv"):
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / name).open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CLAIM_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


@pytest.fixture
def staging(tmp_path):
    for batch in BATCHES:
        path = tmp_path / batch
        write_claims(path.parent, [], path.name)
    return tmp_path


MEMBER_IDS = {m["id"] for m in PlayZoneCatalog(REPO_ROOT).load_bias_radar_members()}


def test_only_supported_persona_claims_are_kept(staging):
    write_claims(
        staging / "member_evidence_v1_1",
        [
            claim("keep"),
            claim("pending", verification_status="pending", usable_for_persona="no"),
            claim("single", usable_for_persona="via_aggregate"),
            claim("self", perspective="self_view"),
        ],
    )
    assert [r["evidence_id"] for r in collect(staging, MEMBER_IDS)] == ["keep"]


def test_later_batch_and_clean_overlay_win(staging):
    write_claims(staging / "member_evidence_v1_2", [claim("a"), claim("b")])
    write_claims(staging / "member_evidence_v1_3", [claim("a", verification_status="pending")])
    write_claims(staging / CLEAN_OVERLAY / "v1_2", [claim("b", value="粉絲常說她（清理版）")])
    rows = collect(staging, MEMBER_IDS)
    assert [(r["evidence_id"], r["value"]) for r in rows] == [("b", "粉絲常說她（清理版）")]


def test_versioned_recheck_replaces_the_original_claim(staging):
    write_claims(staging / "appearance_v3", [claim("a"), claim("b"), claim("c")])
    write_claims(
        staging / "appearance_claims_v5_cafe_recheck",
        [
            claim("a-v5", verification_status="superseded"),
            claim("c-v5", value="粉絲常說她（重核）"),
        ],
        "member_claims_v5_changes.csv",
    )
    write_claims(
        staging / "appearance_claims_v6_source_recheck",
        [claim("a-v5-v6")],
        "member_claims_v6_changes.csv",
    )
    rows = collect(staging, MEMBER_IDS)
    assert [(r["evidence_id"], r["value"]) for r in rows] == [
        ("a-v5-v6", "粉絲常說她親切"),
        ("b", "粉絲常說她親切"),
        ("c-v5", "粉絲常說她（重核）"),
    ]


def test_unknown_member_stops_the_build(staging):
    write_claims(staging / "member_evidence_v1_1", [claim("x", member_id="nobody")])
    with pytest.raises(SystemExit):
        collect(staging, MEMBER_IDS)


def test_query_facets_read_contrast_and_variety_cues():
    assert query_facets("平常安靜，上台像變了一個人") == ["contrast", "offstage_public"]
    assert query_facets("想找綜藝很好笑的") == ["variety"]


def test_pick_prefers_asked_facet_then_fan_perception():
    rows = [
        claim("event", facet="variety", perspective="event_record", value="主持節目"),
        claim("vocal", facet="vocal", value="粉絲常稱讚她的高音"),
        claim("fan", facet="variety", value="粉絲常說她綜藝很好笑", source_count="5"),
    ]
    picked = pick_member_evidence(rows, "綜藝感強的人", limit=2)
    assert [r["claim_id"] for r in picked] == ["fan", "event"]


def test_shipped_evidence_table_loads_and_covers_catalog_members():
    evidence = load_member_evidence(REPO_ROOT)
    assert evidence and set(evidence) <= MEMBER_IDS
    assert all(r["perspective"] != "self_view" for rows in evidence.values() for r in rows)


def test_missing_evidence_table_means_no_evidence(tmp_path):
    assert load_member_evidence(tmp_path) == {}
