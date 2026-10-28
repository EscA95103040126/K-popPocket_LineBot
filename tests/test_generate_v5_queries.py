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


def test_queries_parse_from_object_or_bare_list():
    assert gen._parse_queries('```json\n{"queries": ["甲句子", 3]}\n```') == ["甲句子"]
    assert gen._parse_queries('["乙句子"]') == ["乙句子"]
    assert gen._parse_queries("這是說明文字") == []


def test_old_prompt_version_rows_are_regenerated(tmp_path, monkeypatch):
    output = tmp_path / "q.csv"
    gen._write_rows(
        output,
        [
            {
                "member_id": "twice-sana",
                "evidence_id": "a",
                "facet": "vibe",
                "query": "舊句子",
                "generator": "taide",
                "prompt_version": "v5-evidence-1",
            },
            {
                "member_id": "twice-sana",
                "evidence_id": "a",
                "facet": "vibe",
                "query": "別的模型",
                "generator": "gemma4",
                "prompt_version": "v5-evidence-1",
            },
        ],
    )
    evidence = tmp_path / "e.csv"
    gen._write_rows(evidence, [])
    evidence.write_text(
        "evidence_id,member_id,facet,perspective,value,source_count\n"
        "a,twice-sana,vibe,fan_perception,粉絲常說她親切,3\n",
        encoding="utf-8",
    )
    members = tmp_path / "m.csv"
    members.write_text(
        "id,artist,member,gender_group\ntwice-sana,TWICE,SANA,female\n", encoding="utf-8"
    )
    monkeypatch.setattr(gen, "_generate", lambda args, prompt: ["有沒有很親切的女生成員"])
    monkeypatch.setattr(
        "sys.argv",
        [
            "gen",
            "--model",
            "taide",
            "--evidence",
            str(evidence),
            "--members",
            str(members),
            "--aliases",
            str(tmp_path / "none.csv"),
            "--output",
            str(output),
        ],
    )
    gen.main()
    rows = gen._read_csv(output)
    assert [(r["generator"], r["query"], r["prompt_version"]) for r in rows] == [
        ("gemma4", "別的模型", "v5-evidence-1"),
        ("taide", "有沒有很親切的女生成員", gen.PROMPT_VERSION),
    ]


RAP = {"facet": "performance", "value": "粉絲視她為團內的饒舌擔當，但對她的饒舌實力意見分歧"}
CONTRAST = {"facet": "contrast", "value": "社群說她舞臺上氣場強烈，舞臺外或綜藝裡卻爽朗、親切"}


@pytest.mark.parametrize(
    ("claim_row", "query", "kept"),
    [
        (RAP, "想找饒舌很有記憶點的女生", True),
        # TAIDE 試跑實際寫出的句子：主唱、私下都不在證據裡。
        (RAP, "有沒有團裡有主唱感覺，舞台上氣場超強，但私下又很chill的人？", False),
        (RAP, "有沒有那種舞台上超幹練，但饒舌評價蠻兩極的表演者？", False),
        (CONTRAST, "想找舞台超會演，但是私下很親切的女團成員～", True),
        # 證據講的是綜藝裡親切，不是搞笑。
        (CONTRAST, "想找舞台上氣勢超強，但綜藝裡超ㄎ一ㄤ的女生", False),
        (CONTRAST, "有沒有人知道，有沒有那種公開跟私下反差很大的女生？", False),
    ],
)
def test_queries_must_stay_on_the_sourced_trait(claim_row, query, kept):
    assert gen.stays_on_trait(query, claim_row) is kept
