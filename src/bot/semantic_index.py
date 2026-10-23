"""Semantic member index for AI 入坑 v2.

v1 squeezes a query into ~34 fixed tags before ranking, so anything outside the tag
table is lost. Here every bias radar member gets an open-vocabulary document (Gemini
profile + Grok enrichment, see docs/semantic_curator/PLAN.md) and queries are ranked
by embedding cosine similarity against those documents.

Needs the `curator` dependency group (sentence-transformers, numpy).
"""

from __future__ import annotations

import csv
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

CURATOR_DATA_DIR = Path("data") / "curator"
PROFILES_FILENAME = "member_profiles.csv"
ENRICHMENT_FILENAME = "grok_enrichment.csv"
GROUPS_FILENAME = "grok_groups.csv"


@dataclass(frozen=True)
class EmbeddingModelSpec:
    name: str
    query_prompt: str = ""
    document_prompt: str = ""


# Prompts follow each model card; bge-small-zh was trained with this exact
# (simplified Chinese) retrieval instruction, so it is kept verbatim.
EMBEDDING_MODELS: dict[str, EmbeddingModelSpec] = {
    "bge-small-zh": EmbeddingModelSpec(
        "BAAI/bge-small-zh-v1.5", query_prompt="为这个句子生成表示以用于检索相关文章："
    ),
    "e5-small": EmbeddingModelSpec(
        "intfloat/multilingual-e5-small", query_prompt="query: ", document_prompt="passage: "
    ),
    "bge-m3": EmbeddingModelSpec("BAAI/bge-m3"),
    "qwen3-0.6b": EmbeddingModelSpec(
        "Qwen/Qwen3-Embedding-0.6B",
        query_prompt=(
            "Instruct: Given a K-pop fan's description of what they like, retrieve the "
            "idol member profile that best matches it\nQuery:"
        ),
    ),
}

GENDER_LABELS = {"female": "女團成員", "male": "男團成員"}


def load_member_documents(
    base_dir: Path,
    members: list[dict[str, str]],
    *,
    include_enrichment: bool = True,
) -> dict[str, str]:
    """Build one retrieval document per member id from the curator CSVs."""

    data_dir = base_dir / CURATOR_DATA_DIR
    profiles = {row["id"]: row for row in _read_csv(data_dir / PROFILES_FILENAME)}
    enrichments = (
        {row["id"]: row for row in _read_csv(data_dir / ENRICHMENT_FILENAME)}
        if include_enrichment
        else {}
    )
    documents = {}
    for member in members:
        member_id = member["id"]
        profile = profiles.get(member_id)
        if not profile:
            continue
        documents[member_id] = build_member_document(member, profile, enrichments.get(member_id))
    return documents


def load_group_documents(base_dir: Path) -> dict[str, str]:
    """One document per artist describing the group's concept, music and listening mood."""

    rows = _read_csv(base_dir / CURATOR_DATA_DIR / GROUPS_FILENAME)
    return {row["artist"]: build_group_document(row) for row in rows if row.get("artist")}


def build_member_document(
    member: dict[str, str],
    profile: dict[str, str],
    enrichment: dict[str, str] | None = None,
) -> str:
    gender = GENDER_LABELS.get(member.get("gender_group", ""), "")
    lines = [
        f"{member.get('artist', '')} {member.get('member', '')}，{gender}".strip("，"),
        profile.get("profile", ""),
        "關鍵字：" + "、".join(_split(profile.get("keywords", ""))),
    ]
    if enrichment:
        lines.append(enrichment.get("enrichment", ""))
        if similar := _split(enrichment.get("similar_to", "")):
            lines.append("風格相近：" + "、".join(similar))
        if fan_terms := _split(enrichment.get("fan_terms", "")):
            lines.append("粉絲常說：" + "、".join(fan_terms))
    return "\n".join(line for line in lines if line)


def build_group_document(group: dict[str, str]) -> str:
    lines = [f"{group.get('artist', '')}：{group.get('concept', '')}"]
    for label, field in (
        ("曲風", "music_style"),
        ("代表曲", "signature_songs"),
        ("適合情境", "listener_mood"),
        ("風格相近", "similar_groups"),
        ("團體標籤", "fan_tags"),
    ):
        if values := _split(group.get(field, "")):
            lines.append(f"{label}：" + "、".join(values))
    return "\n".join(lines)


class SemanticMemberIndex:
    """Cosine-similarity ranking of members for a free-text query.

    Group documents are scored separately and added to each member's score with
    `group_weight`. Appending the group text to every member document instead made
    members of one group near-identical and drowned out what sets them apart.
    """

    def __init__(
        self,
        model_key: str,
        documents: dict[str, str],
        group_documents: dict[str, str] | None = None,
        member_artists: dict[str, str] | None = None,
    ) -> None:
        from sentence_transformers import SentenceTransformer

        self.spec = EMBEDDING_MODELS[model_key]
        self.model = SentenceTransformer(self.spec.name)
        self.member_ids = list(documents)
        self.document_embeddings = self._encode(
            [documents[member_id] for member_id in self.member_ids], self.spec.document_prompt
        )
        self.member_artists = member_artists or {}
        self.artists = list(group_documents or {})
        self.group_embeddings = (
            self._encode([group_documents[a] for a in self.artists], self.spec.document_prompt)
            if self.artists
            else None
        )

    def scores(self, query: str, group_weight: float = 0.0) -> dict[str, float]:
        query_embedding = self._encode([query], self.spec.query_prompt)[0]
        similarities = self.document_embeddings @ query_embedding
        group_scores: dict[str, float] = {}
        if group_weight and self.group_embeddings is not None:
            group_similarities = self.group_embeddings @ query_embedding
            group_scores = {
                artist: float(score)
                for artist, score in zip(self.artists, group_similarities, strict=True)
            }
        return {
            member_id: float(score)
            + group_weight * group_scores.get(self.member_artists.get(member_id, ""), 0.0)
            for member_id, score in zip(self.member_ids, similarities, strict=True)
        }

    def rank(self, query: str, group_weight: float = 0.0) -> list[str]:
        scores = self.scores(query, group_weight)
        return sorted(scores, key=scores.__getitem__, reverse=True)

    def _encode(self, texts: list[str], prompt: str):
        return self.model.encode(
            texts, prompt=prompt or None, normalize_embeddings=True, convert_to_numpy=True
        )


FEMALE_QUERY_CUES = ("女團", "女生", "女偶像", "女idol", "女孩", "女歌手", "女rapper")
MALE_QUERY_CUES = ("男團", "男生", "男偶像", "男idol", "男孩", "男歌手", "男rapper")
# Phrases that turn a mentioned artist into a reference point ("像 X 那種") rather
# than the thing the user wants more of.
OTHER_ARTIST_CUES = (
    "別團",
    "別的",
    "其他",
    "另一",
    "再認識",
    "還有哪",
    "還有誰",
    "還可以",
    "類似",
    "一樣",
    "那種",
    "那樣",
)


def apply_query_rules(
    query: str,
    ranked_ids: list[str],
    members_by_id: dict[str, dict[str, str]],
    *,
    exclude_referenced: bool = True,
) -> list[str]:
    """Push members that contradict explicit query constraints to the back.

    Embeddings blur two things users state outright: the gender of the group they
    want, and that an artist they name is a reference point, not the answer.
    """

    compact = _compact(query)
    gender = query_gender(compact)
    excluded_artists = (
        referenced_artists(compact, members_by_id.values())
        if exclude_referenced and any(cue in compact for cue in OTHER_ARTIST_CUES)
        else set()
    )

    def violates(member_id: str) -> bool:
        member = members_by_id.get(member_id, {})
        if gender and member.get("gender_group") != gender:
            return True
        return member.get("artist", "") in excluded_artists

    return [i for i in ranked_ids if not violates(i)] + [i for i in ranked_ids if violates(i)]


def query_gender(compact_query: str) -> str | None:
    female = any(cue in compact_query for cue in FEMALE_QUERY_CUES)
    male = any(cue in compact_query for cue in MALE_QUERY_CUES)
    if female == male:
        return None
    return "female" if female else "male"


def referenced_artists(compact_query: str, members) -> set[str]:
    """Artists named in the query, directly or through one of their members."""

    artists = set()
    for member in members:
        for name in (member.get("artist", ""), member.get("member", "")):
            if name and _mentions(compact_query, name):
                artists.add(member["artist"])
    return artists


def _mentions(compact_query: str, name: str) -> bool:
    needle = re.escape(_compact(name))
    # Romanized names like "V" or "DK" must not match inside longer English words.
    return re.search(rf"(?<![a-z0-9]){needle}(?![a-z0-9])", compact_query) is not None


def _compact(text: str) -> str:
    return unicodedata.normalize("NFKC", text).casefold().replace(" ", "")


def _split(value: str) -> list[str]:
    return [part.strip() for part in value.split("|") if part.strip()]


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as file:
        return list(csv.DictReader(file))
