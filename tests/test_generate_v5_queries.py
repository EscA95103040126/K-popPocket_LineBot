"""v5 訓練問句只收推坑特質、不點名，每位成員的證據數有上限。"""

import pytest

from scripts import generate_v5_queries as gen

MEMBERS = {
    "twice-sana": {
        "id": "twice-sana",
        "artist": "TWICE",
        "member": "SANA",
        "gender_group": "female",
    },
    "bts-v": {"id": "bts-v", "artist": "BTS", "member": "V", "gender_group": "male"},
}


def claim(evidence_id, member_id="twice-sana", perspective="fan_perception", sources="3"):
    return {
        "evidence_id": evidence_id,
        "member_id": member_id,
        "facet": "vibe",
        "perspective": perspective,
        "value": "粉絲常說她親切又愛撒嬌",
        "source_count": sources,
    }


@pytest.fixture(autouse=True)
def no_opencc(monkeypatch):
    class Identity:
        def convert(self, text):
            return text

    monkeypatch.setattr(gen, "_to_taiwan", lambda: Identity())


def test_event_records_and_unknown_members_are_skipped():
    rows = [claim("a"), claim("b", perspective="event_record"), claim("c", member_id="x")]
    assert [r["evidence_id"] for r in gen.select_claims(rows, MEMBERS)] == ["a"]


def test_claims_per_member_are_capped_by_source_count():
    rows = [claim(f"c{n}", sources=str(n)) for n in range(1, 7)]
    picked = gen.select_claims(rows, MEMBERS)
    assert [r["evidence_id"] for r in picked] == ["c6", "c5", "c4", "c3"]


def test_queries_naming_any_member_or_group_are_dropped():
    banned = gen.banned_names(MEMBERS, [{"aliases": "사나|湊崎紗夏"}])
    queries = gen.clean_queries(
        [
            "有沒有很會撒嬌又親切的女生",
            "想找像 SANA 那樣親切的成員",
            "TWICE 裡最親切的是誰",
            "像湊崎紗夏那種甜甜的人",
            "有沒有很會撒嬌又親切的女生",
            "太短了",
            "想找 very 親切、很愛撒嬌的男生",
        ],
        banned,
    )
    # 「V」太短不列入禁用，否則 very 這種一般英文字也會被刪。
    assert queries == ["有沒有很會撒嬌又親切的女生", "想找 very 親切、很愛撒嬌的男生"]


def test_prompt_names_the_trait_but_not_the_member():
    prompt = gen.build_prompt(claim("a"), MEMBERS["twice-sana"])
    assert "粉絲常說她親切又愛撒嬌" in prompt
    assert "SANA" not in prompt and "TWICE" not in prompt
