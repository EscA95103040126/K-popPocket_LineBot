"""Semantic member index for AI 入坑 v2.

v1 squeezes a query into ~34 fixed tags before ranking, so anything outside the tag
table is lost. Here every bias radar member gets an open-vocabulary document (Gemini
profile + Grok enrichment, see docs/semantic_curator/PLAN.md) and queries are ranked
by embedding cosine similarity against those documents.

Two encoders produce the embeddings: `SentenceTransformerEncoder` (the `curator`
dependency group, for comparing models offline) and `OnnxEncoder`, the int8 bge-m3
the bot ships, which only needs onnxruntime, tokenizers and numpy.
"""

from __future__ import annotations

import csv
import hashlib
import json
import logging
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

CURATOR_DATA_DIR = Path("data") / "curator"
PROFILES_FILENAME = "member_profiles.csv"
ENRICHMENT_FILENAME = "grok_enrichment.csv"
GROUPS_FILENAME = "grok_groups.csv"
ONNX_ENCODER_DIR = Path("models") / "bge-m3-int8"
ONNX_MAX_TOKENS = 512
MEMBER_EMBEDDINGS_FILENAME = "member_embeddings.npz"
NOTE_PROFILE_CHARS = 70
NOTE_CONCEPT_CHARS = 110


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

# The int8 ONNX export of bge-m3 built by scripts/export_onnx_encoder.py.
ONNX_MODEL_KEY = "bge-m3-int8"

GENDER_LABELS = {"female": "女團成員", "male": "男團成員"}


class SentenceTransformerEncoder:
    def __init__(self, model_key: str) -> None:
        from sentence_transformers import SentenceTransformer

        self.spec = EMBEDDING_MODELS[model_key]
        self.model = SentenceTransformer(self.spec.name)

    def encode_queries(self, texts: list[str]):
        return self._encode(texts, self.spec.query_prompt)

    def encode_documents(self, texts: list[str]):
        return self._encode(texts, self.spec.document_prompt)

    def _encode(self, texts: list[str], prompt: str):
        return self.model.encode(
            texts, prompt=prompt or None, normalize_embeddings=True, convert_to_numpy=True
        )


class OnnxEncoder:
    """bge-m3 (no query/document prompts) through onnxruntime on CPU."""

    def __init__(self, model_dir: Path, threads: int | None = None) -> None:
        import onnxruntime
        from tokenizers import Tokenizer

        options = onnxruntime.SessionOptions()
        if threads:
            options.intra_op_num_threads = threads
        self.session = onnxruntime.InferenceSession(
            str(model_dir / "model.onnx"), options, providers=["CPUExecutionProvider"]
        )
        self.tokenizer = Tokenizer.from_file(str(model_dir / "tokenizer.json"))
        self.tokenizer.enable_truncation(ONNX_MAX_TOKENS)
        self.tokenizer.enable_padding(pad_id=self.tokenizer.token_to_id("<pad>"))

    def encode_queries(self, texts: list[str]):
        return self._encode(texts)

    def encode_documents(self, texts: list[str]):
        # One at a time: padding a batch to its longest document wastes CPU.
        import numpy

        return numpy.vstack([self._encode([text]) for text in texts])

    def _encode(self, texts: list[str]):
        import numpy

        encodings = self.tokenizer.encode_batch(texts)
        (embeddings,) = self.session.run(
            ["sentence_embedding"],
            {
                "input_ids": numpy.array([e.ids for e in encodings], dtype=numpy.int64),
                "attention_mask": numpy.array(
                    [e.attention_mask for e in encodings], dtype=numpy.int64
                ),
            },
        )
        return embeddings / numpy.linalg.norm(embeddings, axis=1, keepdims=True)


def build_encoder(model_key: str, base_dir: Path | None = None):
    if model_key == ONNX_MODEL_KEY:
        return OnnxEncoder((base_dir or Path(".")) / ONNX_ENCODER_DIR)
    return SentenceTransformerEncoder(model_key)


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
        encoder,
        documents: dict[str, str],
        group_documents: dict[str, str] | None = None,
        member_artists: dict[str, str] | None = None,
        document_embeddings=None,
    ) -> None:
        self.encoder = encoder
        self.member_ids = list(documents)
        # Encoding 154 documents takes about a minute on CPU, so the bot passes the
        # embeddings scripts/build_member_embeddings.py precomputed.
        self.document_embeddings = (
            document_embeddings
            if document_embeddings is not None
            else encoder.encode_documents([documents[member_id] for member_id in self.member_ids])
        )
        self.member_artists = member_artists or {}
        self.artists = list(group_documents or {})
        self.group_embeddings = (
            encoder.encode_documents([group_documents[a] for a in self.artists])
            if self.artists
            else None
        )

    def scores(self, query: str, group_weight: float = 0.0) -> dict[str, float]:
        query_embedding = self.encoder.encode_queries([query])[0]
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


def documents_digest(documents: dict[str, str]) -> str:
    """Fingerprint of the member documents, to detect stale precomputed embeddings."""

    payload = json.dumps(documents, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def write_member_embeddings(base_dir: Path, members: list[dict[str, str]], encoder) -> Path:
    import numpy

    documents = load_member_documents(base_dir, members)
    member_ids = list(documents)
    embeddings = encoder.encode_documents([documents[member_id] for member_id in member_ids])
    path = base_dir / ONNX_ENCODER_DIR / MEMBER_EMBEDDINGS_FILENAME
    numpy.savez(
        path,
        member_ids=numpy.array(member_ids),
        embeddings=embeddings.astype(numpy.float32),
        digest=numpy.array(documents_digest(documents)),
    )
    return path


class SemanticMemberRanker:
    """What the bot uses at runtime: v2 ranking plus short notes for the answer prompt.

    The v2 setup that won the offline evaluation (docs/semantic_curator/PLAN.md):
    int8 bge-m3, Gemini profile + Grok enrichment documents, gender filter only.
    """

    def __init__(
        self,
        index: SemanticMemberIndex,
        members: list[dict[str, str]],
        notes: dict[str, str],
    ) -> None:
        self.index = index
        self.members_by_id = {member["id"]: member for member in members}
        self.notes = notes

    @classmethod
    def load(cls, base_dir: Path, members: list[dict[str, str]]) -> SemanticMemberRanker | None:
        """None when the encoder or embeddings are missing or stale; callers fall back to v1."""

        model_dir = base_dir / ONNX_ENCODER_DIR
        embeddings_path = model_dir / MEMBER_EMBEDDINGS_FILENAME
        if not (model_dir / "model.onnx").exists() or not embeddings_path.exists():
            logger.info("Semantic curator model not found in %s; using v1 ranking.", model_dir)
            return None
        try:
            import numpy

            documents = load_member_documents(base_dir, members)
            stored = numpy.load(embeddings_path)
            if str(stored["digest"]) != documents_digest(documents):
                logger.warning("Member embeddings are stale; rerun build_member_embeddings.py.")
                return None
            member_ids = [str(member_id) for member_id in stored["member_ids"]]
            index = SemanticMemberIndex(
                OnnxEncoder(model_dir),
                {member_id: documents[member_id] for member_id in member_ids},
                document_embeddings=stored["embeddings"],
            )
        except Exception:
            logger.exception("Could not load the semantic curator; using v1 ranking.")
            return None
        return cls(index, members, load_member_notes(base_dir, members))

    def rank(self, query: str) -> list[dict[str, str]]:
        ranked = apply_query_rules(
            query, self.index.rank(query), self.members_by_id, exclude_referenced=False
        )
        return [self.members_by_id[member_id] for member_id in ranked]


def load_member_notes(base_dir: Path, members: list[dict[str, str]]) -> dict[str, str]:
    """One line per member for the Gemini answer prompt: who they are and the group concept.

    Group concepts did not help ranking, but they let the answer explain why a group fits.
    """

    data_dir = base_dir / CURATOR_DATA_DIR
    profiles = {row["id"]: row for row in _read_csv(data_dir / PROFILES_FILENAME)}
    groups = {row["artist"]: row for row in _read_csv(data_dir / GROUPS_FILENAME)}
    notes = {}
    for member in members:
        profile = profiles.get(member["id"], {}).get("profile", "")
        concept = groups.get(member.get("artist", ""), {}).get("concept", "")
        parts = [
            _clip(re.split(r"(?<=[。！？])", profile.strip(), maxsplit=1)[0], NOTE_PROFILE_CHARS),
            # Whole concept, not its first sentence: the hook (e.g. ENHYPEN's vampire
            # worldview) often comes after an opening line about the group's origin.
            _clip(concept, NOTE_CONCEPT_CHARS),
        ]
        if note := "；團體：".join(part for part in parts if part):
            notes[member["id"]] = note
    return notes


def _clip(text: str, limit: int) -> str:
    text = text.strip().rstrip("。")
    return text if len(text) <= limit else text[:limit] + "…"


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
