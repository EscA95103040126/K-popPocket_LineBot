"""實體／意圖的功能約束，不以 demo 理想人選作答案。"""

import pytest

from src.bot.catalog import PlayZoneCatalog
from src.bot.curator_query import CuratorQueryParser
from src.bot.semantic_index import SemanticMemberIndex, SemanticMemberRanker
from tests.fakes import REPO_ROOT
from tests.test_semantic_index import FakeEncoder


@pytest.fixture
def parser():
    return CuratorQueryParser.load(REPO_ROOT, PlayZoneCatalog(REPO_ROOT).load_bias_radar_members())


@pytest.mark.parametrize(
    ("query", "member_id"),
    [
        ("像子瑜那種氣質", "twice-tzuyu"),
        ("找和 카리나 舞台相似的人", "aespa-karina"),
        ("跟 NMIXX Jiwoo 相似的成員", "nmixx-jiwoo"),
        ("跟 Hearts2Hearts 지우 相似的成員", "hearts2hearts-jiwoo"),
        ("像 TXT HUENING KAI 那種聲線", "txt-hueningkai"),
        ("像 NMIXX 的 Kim Jiwoo 那樣", "nmixx-jiwoo"),
    ],
)
def test_aliases_resolve_and_exclude_reference_self(parser, query, member_id):
    parsed = parser.parse(query)
    assert parsed.mode == "similarity"
    assert member_id in parsed.excluded_ids
    assert member_id not in parser.constrain(parsed, list(parser.members))


def test_unqualified_shared_name_stays_ambiguous(parser):
    parsed = parser.parse("找跟 Jiwoo 聲線相似的人")
    assert not parsed.excluded_ids
    assert len(parsed.entities) == 1
    assert len(parsed.entities[0].candidates) == 2
    assert parsed.entities[0].artist is None


def test_two_jiwoos_use_their_own_group_context(parser):
    parsed = parser.parse("NMIXX Jiwoo 跟 Hearts2Hearts Jiwoo 的聲線")
    mentions = [e for e in parsed.entities if e.kind == "member"]
    assert [e.candidates for e in mentions] == [("nmixx-jiwoo",), ("hearts2hearts-jiwoo",)]


@pytest.mark.parametrize(
    "query",
    [
        "love vocal music",
        "live five",
        "open notes.txt",
        "I wish for joy twice",
        "ten songs in a playlist",
    ],
)
def test_common_english_words_do_not_become_entities(parser, query):
    assert not parser.parse(query).entities


def test_same_artist_keeps_members_and_does_not_exclude_song_dislike(parser):
    parsed = parser.parse("喜歡 i-dle〈甲〉但不喜歡〈乙〉，求推薦他們的歌")
    assert parsed.mode == "same_artist"
    assert not parsed.excluded_artists
    assert parser.constrain(parsed, ["twice-sana", "idle-yuqi"])[0] == "idle-yuqi"


def test_intra_group_member_search_does_not_become_cross_group(parser):
    parsed = parser.parse("NMIXX 同團裡跟 Haewon 聲線相似的其他成員")
    assert parsed.mode == "same_artist"
    assert not parsed.excluded_artists
    assert "nmixx-haewon" in parsed.excluded_ids


def test_mentioning_current_favorite_is_not_same_group_request(parser):
    parsed = parser.parse("平常聽 IVE，想找清新風格的女團")
    assert parsed.mode == "general"
    assert not parsed.preferred_artists


def test_similar_to_group_keeps_one_member_of_that_group(parser):
    parsed = parser.parse("想多找跟 RIIZE 風格一樣的歌")
    assert parsed.mode == "similarity"
    assert not parsed.excluded_artists
    ranked = ["riize-sohee", "riize-wonbin", "itzy-ryujin", "itzy-lia"]
    assert parser.constrain(parsed, ranked) == [
        "riize-sohee",
        "itzy-ryujin",
        "itzy-lia",
        "riize-wonbin",
    ]


def test_similar_to_member_keeps_one_groupmate_and_drops_self(parser):
    parsed = parser.parse("我喜歡 MEOVV 的 ANNA，有沒有相似類型的推薦？")
    ranked = ["meovv-anna", "meovv-narin", "meovv-ella", "qwer-hina", "twice-sana"]
    assert parser.constrain(parsed, ranked) == [
        "meovv-narin",
        "qwer-hina",
        "twice-sana",
        "meovv-ella",
    ]


def test_asking_for_other_groups_drops_the_reference_group(parser):
    parsed = parser.parse("喜歡 MEOVV ANNA，想認識其他團像她的人")
    assert "MEOVV" in parsed.excluded_artists
    assert parser.constrain(parsed, ["meovv-narin", "qwer-hina"]) == ["qwer-hina"]


def test_explicit_group_exclusion_is_hard_filter(parser):
    parsed = parser.parse("除了 NMIXX 之外，想找其他女團")
    assert "NMIXX" in parsed.excluded_artists
    assert parser.constrain(parsed, ["nmixx-lily", "twice-sana"]) == ["twice-sana"]


def test_song_section_is_not_artist_exclusion(parser):
    parsed = parser.parse("像 TXT〈甲〉副歌以外的吉他編曲")
    assert parsed.mode == "related_music"
    assert not parsed.excluded_artists


def test_song_title_is_not_resolved_as_group_alias(parser):
    parsed = parser.parse("喜歡 MEOVV〈MEOW〉，推薦他們的歌")
    assert len(parsed.entities) == 1
    assert "〈MEOW〉" in parsed.search_query


def test_visual_is_marked_out_of_scope(parser):
    parsed = parser.parse("跟子瑜長得像的人")
    assert parsed.mode == "unsupported_visual"
    assert not parsed.facets


def test_alias_table_missing_or_invalid_falls_back(tmp_path):
    members = PlayZoneCatalog(REPO_ROOT).load_bias_radar_members()
    parser = CuratorQueryParser.load(tmp_path, members)
    assert parser.parse("像 TWICE SANA 的人").excluded_ids == {"twice-sana"}
    parser = CuratorQueryParser(
        members,
        [{"entity_type": "member", "canonical": "unknown", "group": "TWICE", "aliases": "幽靈"}],
    )
    assert not parser.parse("像幽靈的人").entities


def test_alias_table_can_be_loaded_from_staging(tmp_path):
    folder = tmp_path / "data/curator/staging/grok"
    folder.mkdir(parents=True)
    (folder / "grok_aliases.csv").write_text(
        "entity_type,canonical,group,aliases\nmember,twice-tzuyu,TWICE,測試別名\n"
    )
    parser = CuratorQueryParser.load(tmp_path, PlayZoneCatalog(REPO_ROOT).load_bias_radar_members())
    assert "twice-tzuyu" in parser.parse("像測試別名的人").excluded_ids


def test_ranker_applies_same_constraints_as_runtime(parser):
    members = list(parser.members.values())
    index = SemanticMemberIndex(FakeEncoder(), {"twice-sana": "甜", "nmixx-lily": "冷"})
    ranker = SemanticMemberRanker(index, members, {}, parser)
    assert ranker.rank_ids("像 TWICE SANA 那種甜系") == ["nmixx-lily"]
    assert [m["id"] for m in ranker.rank("像 TWICE SANA 那種甜系")] == ["nmixx-lily"]
