import random
from pathlib import Path

import numpy
import pytest

from src.bot.catalog import PlayZoneCatalog
from src.bot.features.ai_curator import AiCuratorFeature
from src.bot.semantic_index import (
    MEMBER_EMBEDDINGS_FILENAME,
    ONNX_ENCODER_DIR,
    SemanticMemberIndex,
    SemanticMemberRanker,
    _compact,
    apply_query_rules,
    build_member_document,
    load_member_notes,
    query_gender,
    referenced_artists,
)
from src.bot.sessions import InMemorySessionStore
from tests.fakes import REPO_ROOT, FakeLlm

MEMBERS = {
    "aespa-karina": {
        "id": "aespa-karina",
        "artist": "aespa",
        "member": "KARINA",
        "gender_group": "female",
    },
    "bts-v": {"id": "bts-v", "artist": "BTS", "member": "V", "gender_group": "male"},
    "twice-sana": {
        "id": "twice-sana",
        "artist": "TWICE",
        "member": "SANA",
        "gender_group": "female",
    },
}


class FakeEncoder:
    """Embeds text onto fixed axes by keyword, so rankings are easy to predict."""

    AXES = ("冷", "甜", "低沉")

    def __init__(self) -> None:
        self.document_calls = 0

    def encode_queries(self, texts):
        return self._encode(texts)

    def encode_documents(self, texts):
        self.document_calls += 1
        return self._encode(texts)

    def _encode(self, texts):
        vectors = numpy.array(
            [[1.0 if axis in text else 0.0 for axis in self.AXES] + [0.1] for text in texts]
        )
        return vectors / numpy.linalg.norm(vectors, axis=1, keepdims=True)


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("我喜歡甜甜的女生", "female"),
        ("推薦 vocal 強的男團", "male"),
        ("男生女生都可以", None),
        ("想找清冷感的偶像", None),
    ],
)
def test_query_gender_reads_explicit_cues(query: str, expected: str | None) -> None:
    assert query_gender(_compact(query)) == expected


def test_apply_query_rules_moves_wrong_gender_to_the_back() -> None:
    ranked = ["bts-v", "aespa-karina", "twice-sana"]

    assert apply_query_rules("甜甜的女生", ranked, MEMBERS) == [
        "aespa-karina",
        "twice-sana",
        "bts-v",
    ]


def test_apply_query_rules_can_keep_referenced_artists() -> None:
    ranked = ["aespa-karina", "twice-sana"]
    query = "喜歡 aespa 那種"

    assert apply_query_rules(query, ranked, MEMBERS) == ["twice-sana", "aespa-karina"]
    assert apply_query_rules(query, ranked, MEMBERS, exclude_referenced=False) == ranked


def test_referenced_artists_does_not_match_short_names_inside_words() -> None:
    assert referenced_artists(_compact("想找 vocal 很強的人"), MEMBERS.values()) == set()
    assert referenced_artists(_compact("喜歡 V 的聲音"), MEMBERS.values()) == {"BTS"}


def test_build_member_document_includes_enrichment() -> None:
    document = build_member_document(
        MEMBERS["aespa-karina"],
        {"profile": "冷豔的主舞。", "keywords": "冷感|主舞"},
        {"enrichment": "Supernova 舞台。", "similar_to": "IVE WONYOUNG", "fan_terms": "AI臉"},
    )

    assert document.splitlines() == [
        "aespa KARINA，女團成員",
        "冷豔的主舞。",
        "關鍵字：冷感、主舞",
        "Supernova 舞台。",
        "風格相近：IVE WONYOUNG",
        "粉絲常說：AI臉",
    ]


def test_semantic_index_ranks_by_similarity_and_reuses_precomputed_embeddings() -> None:
    encoder = FakeEncoder()
    documents = {"aespa-karina": "冷", "twice-sana": "甜", "bts-v": "低沉"}
    index = SemanticMemberIndex(encoder, documents)
    precomputed = SemanticMemberIndex(
        encoder, documents, document_embeddings=index.document_embeddings
    )

    assert index.rank("想找甜甜的")[0] == "twice-sana"
    assert precomputed.rank("聲音低沉")[0] == "bts-v"
    assert encoder.document_calls == 1


def test_semantic_index_group_weight_lifts_members_of_matching_group() -> None:
    documents = {"aespa-karina": "冷", "twice-sana": "冷"}
    index = SemanticMemberIndex(
        FakeEncoder(),
        documents,
        group_documents={"aespa": "冷", "TWICE": "甜"},
        member_artists={"aespa-karina": "aespa", "twice-sana": "TWICE"},
    )

    scores = index.scores("冷", group_weight=0.5)

    assert scores["aespa-karina"] > scores["twice-sana"]


def test_ranker_load_returns_none_without_model(tmp_path: Path) -> None:
    assert SemanticMemberRanker.load(tmp_path, list(MEMBERS.values())) is None


def test_ranker_load_returns_none_when_embeddings_are_stale(tmp_path: Path) -> None:
    model_dir = tmp_path / ONNX_ENCODER_DIR
    model_dir.mkdir(parents=True)
    (model_dir / "model.onnx").write_bytes(b"")
    numpy.savez(
        model_dir / MEMBER_EMBEDDINGS_FILENAME,
        member_ids=numpy.array(["aespa-karina"]),
        embeddings=numpy.zeros((1, 4), dtype=numpy.float32),
        digest=numpy.array("outdated"),
    )

    assert SemanticMemberRanker.load(tmp_path, list(MEMBERS.values())) is None


def test_member_notes_join_profile_and_group_concept() -> None:
    members = PlayZoneCatalog(REPO_ROOT).load_bias_radar_members()

    notes = load_member_notes(REPO_ROOT, members)

    assert "；團體：" in notes["enhypen-sunghoon"]
    assert "吸血鬼" in notes["enhypen-sunghoon"]


class FakeRanker:
    def __init__(self, members: list[dict[str, str]]) -> None:
        self.members = members
        self.notes = {members[0]["id"]: "測試用簡介"}
        self.queries: list[str] = []

    def rank(self, query: str) -> list[dict[str, str]]:
        self.queries.append(query)
        return self.members


def _curator(llm: FakeLlm, loader) -> AiCuratorFeature:
    return AiCuratorFeature(
        PlayZoneCatalog(REPO_ROOT),
        llm,
        random.Random(0),
        InMemorySessionStore(),
        is_fixed_command=lambda _message: False,
        semantic_ranker_loader=loader,
    )


def test_ai_curator_uses_semantic_ranker_and_one_gemini_call() -> None:
    catalog_members = {m["id"]: m for m in PlayZoneCatalog(REPO_ROOT).load_bias_radar_members()}
    ranked = [catalog_members["twice-sana"], catalog_members["twice-nayeon"]]
    ranker = FakeRanker(ranked)
    loads = []
    llm = FakeLlm(text='["笑起來超有感染力，甜度滿分", "https://not.a/reason"]')
    curator = _curator(llm, lambda: loads.append(1) or ranker)

    context = curator._build_ai_curator_context("我喜歡甜甜的女生")
    response = curator._ai_curator_response("我喜歡甜甜的女生")

    assert [m["id"] for m in context["member_candidates"]] == ["twice-sana", "twice-nayeon"]
    assert context["profile"]["gender"] == "female"
    assert context["low_confidence"] is False
    # Only the answer prompt: v2 skips the Gemini tag-profile parse.
    assert len(llm.prompts) == 1
    prompt_lines = llm.prompts[0].splitlines()
    # The curated note replaces the v1 tags; members without one keep the tags.
    assert "1. TWICE SANA：測試用簡介" in prompt_lines
    assert any(line.startswith("2. TWICE NAYEON: position=") for line in prompt_lines)
    # Gemini's reasons fill the fixed layout; an unusable one falls back to the tags.
    report_lines = response["report"].splitlines()
    assert report_lines[:3] == [
        "🧭 AI 入坑",
        "根據你說的「我喜歡甜甜的女生」，我會這樣排：",
        "1. TWICE SANA：笑起來超有感染力，甜度滿分。",
    ]
    assert report_lines[3].startswith("2. TWICE NAYEON：") and "適合先看本命雷達" in report_lines[3]
    assert report_lines[4].startswith("今日入口：先看 ")
    assert loads == [1]


def test_ai_curator_falls_back_to_v1_when_loader_returns_none() -> None:
    curator = _curator(FakeLlm(text=""), lambda: None)

    context = curator._build_ai_curator_context("我想入坑清冷感、舞台強的女團")

    assert context["member_candidates"]
    assert context["member_notes"] == {}


def test_daily_entry_excludes_hidden_candidate_groups() -> None:
    members = {m["id"]: m for m in PlayZoneCatalog(REPO_ROOT).load_bias_radar_members()}
    ranked = [
        members[i] for i in ("meovv-anna", "meovv-narin", "meovv-ella", "qwer-hina", "idle-yuqi")
    ]
    curator = _curator(FakeLlm(text=""), lambda: FakeRanker(ranked))

    for seed in range(20):
        curator.rng.seed(seed)
        context = curator._build_ai_curator_context("我喜歡 MEOVV 的 ANNA，有沒有相似類型的推薦？")
        assert context["recommended_artists"] == ["MEOVV"]
        assert context["daily_items"]
        assert all(item["artist"] == "MEOVV" for item in context["daily_items"])


def test_daily_entry_matches_artist_case_and_spacing() -> None:
    curator = _curator(FakeLlm(text=""), lambda: None)
    rows = curator._rank_daily_mv_rows_for_artists(["  meovv  "], {})
    assert rows and all(row["artist"] == "MEOVV" for row in rows)


def test_daily_entry_omitted_when_recommended_artist_has_no_mv() -> None:
    curator = _curator(FakeLlm(text=""), lambda: None)
    assert curator._rank_daily_mv_rows_for_artists(["測試用無 MV 團體"], {}) == []


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("我喜歡比較年輕的，唱歌比較好的那種", True),
        ("有沒有聲音很特別的人", True),
        ("推薦", False),  # too short to describe a preference
        ("今天天氣好熱喔", False),  # no preference cue
        ("本命雷達測驗", False),  # fixed command
        ("為什麼推薦 Karina", False),  # reason follow-up has its own route
    ],
)
def test_free_text_preference_needs_a_cue_and_no_command(message: str, expected: bool) -> None:
    from src.bot.dispatcher import MessageContext
    from src.bot.routing import is_fixed_command

    curator = AiCuratorFeature(
        PlayZoneCatalog(REPO_ROOT),
        FakeLlm(),
        random.Random(0),
        InMemorySessionStore(),
        is_fixed_command=is_fixed_command,
    )

    assert curator.is_ai_curator_free_text_preference(MessageContext(message, "U1")) is expected


def test_parse_reasons_keeps_one_clean_line_per_member() -> None:
    from src.bot.features.ai_curator import _parse_ai_curator_reasons

    text = """```json
["1. 出道曲〈Get A Guitar〉就和吉他有關", "Plays guitar in a band", "身為樂團成員，現場彈奏超有魅力！"]
```"""

    assert _parse_ai_curator_reasons(text, 4) == [
        "出道曲〈Get A Guitar〉就和吉他有關。",
        None,  # not Chinese
        "身為樂團成員，現場彈奏超有魅力！",
        None,  # Gemini returned fewer reasons than members
    ]
    assert _parse_ai_curator_reasons("not json", 2) == [None, None]


def test_llm_error_logs_status_without_the_api_key() -> None:
    import requests

    from src.bot.features.ai_curator import _llm_error

    response = requests.Response()
    response.status_code = 429
    error = requests.HTTPError(
        "429 for url: https://x/generateContent?key=SECRET", response=response
    )

    assert _llm_error(error) == "HTTP 429"
    assert _llm_error(requests.Timeout("timed out ?key=SECRET")) == "Timeout"
