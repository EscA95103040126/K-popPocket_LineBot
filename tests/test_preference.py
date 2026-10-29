"""偏好解析：只用有來源的特質，否定降權不刪除，排除團和參照成員。"""

import json

import pytest

from src.bot.catalog import PlayZoneCatalog
from src.bot.curator_query import CuratorQueryParser
from src.bot.member_evidence import load_member_evidence
from src.bot.preference import (
    Preference,
    PreferenceCache,
    PreferenceParser,
    Trait,
    adjust_scores,
    filter_ranked,
    load_trait_tags,
    tag_members,
    validate,
)
from tests.fakes import REPO_ROOT

MEMBERS = PlayZoneCatalog(REPO_ROOT).load_bias_radar_members()
BY_ID = {m["id"]: m for m in MEMBERS}
TAGS = load_trait_tags(REPO_ROOT)


def test_tags_come_only_from_sourced_evidence():
    members_by_tag = tag_members(TAGS, load_member_evidence(REPO_ROOT))
    assert "aespa-karina" in members_by_tag["cat_face"]
    # 每個特質都至少有一位有來源的成員，否則放進特質表也沒有用。
    assert all(members_by_tag[t.tag] for t in TAGS)
    evidence = {
        "twice-sana": [{"facet": "appearance", "perspective": "self_view", "value": "貓系"}]
    }
    assert not tag_members(TAGS, evidence)["cat_face"]


def test_validate_drops_unknown_tags_and_members():
    preference = validate(
        {
            "is_appearance": True,
            "gender": "female",
            "traits": [
                {"tag": "cat_face", "raw": "고양이상", "polarity": "+", "weight": "high"},
                {"tag": "tall", "raw": "키 큰", "polarity": "+", "weight": "mid"},
                {"tag": "rabbit_face", "raw": "토끼상", "polarity": "-", "weight": "weird"},
            ],
            "reference_member_ids": ["aespa-karina", "nobody-x"],
            "exclude_artists": ["blackpink", "Unknown Band"],
            "gender_extra": "ignored",
        },
        TAGS,
        BY_ID,
    )
    assert preference.traits == (
        Trait("cat_face", "고양이상", "+", "high"),
        Trait("rabbit_face", "토끼상", "-", "mid"),
    )
    assert preference.reference_member_ids == ("aespa-karina",)
    assert preference.reference_out_of_catalog == ("nobody-x",)
    assert preference.exclude_artists == ("BLACKPINK",)
    assert "unmapped:키 큰" in preference.non_trait_constraints
    assert validate({"gender": "any"}, TAGS, BY_ID).gender is None


def test_negative_traits_push_down_without_removing():
    scores = {"a": 1.0, "b": 0.9, "c": 0.0}
    preference = Preference(
        traits=(Trait("cat_face", "", "+", "high"), Trait("rabbit_face", "", "-", "mid"))
    )
    members_by_tag = {"cat_face": frozenset({"c"}), "rabbit_face": frozenset({"a"})}
    adjusted = adjust_scores(scores, preference, members_by_tag, bonus=1.0, penalty=1.0)
    assert adjusted == pytest.approx({"a": 0.4, "b": 0.9, "c": 1.0})


def test_filter_removes_excluded_groups_and_references_and_sorts_gender():
    ranked = ["blackpink-jennie", "aespa-karina", "bts-v", "twice-sana"]
    preference = Preference(
        gender="female", reference_member_ids=("aespa-karina",), exclude_artists=("BLACKPINK",)
    )
    assert filter_ranked(ranked, preference, BY_ID) == ["twice-sana", "bts-v"]


class FakeLlm:
    enabled = True

    def __init__(self, reply):
        self.reply = reply
        self.calls = 0

    def generate(self, prompt, **kwargs):
        self.calls += 1
        return self.reply


def test_parser_caches_by_query_and_falls_back_on_bad_json(tmp_path):
    reply = json.dumps({"gender": "male", "traits": [{"tag": "puppy_face", "raw": "강아지상"}]})
    llm = FakeLlm(reply)
    cache = PreferenceCache(tmp_path / "cache.json", "test-model")
    parser = PreferenceParser(llm, TAGS, MEMBERS, cache=cache)

    first = parser.parse("강아지상 남돌")
    assert first.gender == "male"
    assert first.traits == (Trait("puppy_face", "강아지상", "+", "mid"),)
    assert parser.parse("강아지상 남돌") == first
    assert llm.calls == 1

    cache.save()
    offline = PreferenceParser(
        None,
        TAGS,
        MEMBERS,
        cache=PreferenceCache.load(tmp_path / "cache.json", "test-model"),
        live=False,
    )
    assert offline.parse("강아지상 남돌") == first
    assert offline.parse("沒解析過的句子") is None
    # 換模型或提示詞版本都不能拿到別的版本的解析結果；舊版的結果存檔後還在。
    assert PreferenceCache.load(tmp_path / "cache.json", "other-model").get("강아지상 남돌") is None
    old = PreferenceCache.load(tmp_path / "cache.json", "test-model", "pref-old")
    assert old.get("강아지상 남돌") is None
    old.put("강아지상 남돌", Preference(gender="female"))
    old.save()
    reloaded = PreferenceCache.load(tmp_path / "cache.json", "test-model")
    assert reloaded.get("강아지상 남돌") == first

    assert PreferenceParser(FakeLlm("not json"), TAGS, MEMBERS).parse("x") is None


def test_named_members_are_matched_whole_against_the_alias_table():
    # 模型亂填的參照成員 id 不採用；人名只照原文整個比對，不在問句裡找子字串。
    reply = json.dumps(
        {
            "gender": "female",
            "traits": [],
            "reference_member_ids": ["twice-sana"],
            "people": [
                {"name": "카리나", "group": None, "negative": False},
                {"name": "Jiwoo", "group": None, "negative": False},
                {"name": "선우", "group": "더보이즈", "negative": False},
                {"name": "츄", "group": None, "negative": True},
            ],
        }
    )
    parser = PreferenceParser(
        FakeLlm(reply), TAGS, MEMBERS, CuratorQueryParser.load(REPO_ROOT, MEMBERS)
    )
    preference = parser.parse("한 번만 추천해 주세요, 진짜 카리나 같은 사람")
    assert preference.reference_member_ids == ("aespa-karina",)
    assert preference.reference_out_of_catalog == ("Jiwoo", "선우（더보이즈）")
    assert "negative_reference: 츄" in preference.non_trait_constraints
    # 提示詞不附成員表。
    assert not any(member["id"] in parser.prompt("x") for member in MEMBERS)
