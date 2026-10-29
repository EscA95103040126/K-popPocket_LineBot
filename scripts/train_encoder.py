"""Fine-tune bge-m3 on fan queries for AI 入坑 (v3 synthetic queries, v5 evidence queries).

Each query is paired with its member's retrieval document and trained with
CachedGISTEmbedLoss: in-batch negatives as usual, but the frozen base model acts as a
guide and drops negatives it scores above the positive. Queries like 「甜甜的女生」 fit
several members, so plain in-batch negatives would punish the model for matching them.
NO_DUPLICATES keeps two copies of one text out of the same batch.

v5 adds:
- the queries scripts/generate_v5_queries.py wrote from sourced member evidence, paired
  both with the member document and with the evidence text itself, since the index now
  scores every piece of evidence separately (src/bot/semantic_index.py);
- a hard negative per row: a member of the same group. v4 kept ranking a whole group
  together because their documents share the group concept; the guide still drops the
  negative when the base model thinks it fits the query just as well.

Training is LoRA (rank-16 adapters on the attention projections, merged back before
saving). Full fine-tuning of all 568M parameters needed far more than the M1 Pro's
32GB: AdamW state for the 250k-row embedding table alone is ~2GB, and the run spent
hours in swap.

Usage (needs the `curator` dependency group; runs on Apple Silicon MPS):
    uv run --group curator python scripts/train_encoder.py
    uv run --group curator python scripts/export_onnx_encoder.py \\
        --source models/bge-m3-curator-v5 --out models/bge-m3-v5-int8
"""

from __future__ import annotations

import argparse
import csv
import random
import sys
from collections import defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.bot.catalog import PlayZoneCatalog
from src.bot.member_evidence import load_member_evidence
from src.bot.semantic_index import evidence_text, load_member_documents

SYNTHETIC_QUERIES_CSV = PROJECT_ROOT / "data" / "curator" / "synthetic_queries.csv"
V5_QUERIES_CSV = PROJECT_ROOT / "data" / "curator" / "v5_queries.csv"
BASE_MODEL = "BAAI/bge-m3"
DEFAULT_OUTPUT = PROJECT_ROOT / "models" / "bge-m3-curator-v5"
# Member documents run 252-337 tokens; queries are far shorter.
MAX_SEQ_LENGTH = 384
LORA_RANK = 16
LORA_TARGET_MODULES = ["query", "key", "value"]


def build_rows(seed: int) -> list[dict[str, str]]:
    """(anchor, positive, negative) rows; the negative is a member of the same group."""

    rng = random.Random(seed)
    members = PlayZoneCatalog(PROJECT_ROOT).load_bias_radar_members()
    by_id = {member["id"]: member for member in members}
    documents = load_member_documents(PROJECT_ROOT, members)
    groups: dict[str, list[str]] = defaultdict(list)
    for member in members:
        if member["id"] in documents:
            groups[member["artist"]].append(member["id"])
    evidence = {
        row["evidence_id"]: row
        for rows in load_member_evidence(PROJECT_ROOT).values()
        for row in rows
    }
    evidence_by_artist: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in evidence.values():
        evidence_by_artist[by_id[row["member_id"]]["artist"]].append(row)

    def bandmate(member_id: str) -> str:
        others = [i for i in groups[by_id[member_id]["artist"]] if i != member_id]
        return rng.choice(others or [i for i in documents if i != member_id])

    rows = []
    for query in _read_csv(SYNTHETIC_QUERIES_CSV):
        member_id = query["member_id"]
        if member_id in documents:
            rows.append(_row(query["query"], documents[member_id], documents[bandmate(member_id)]))
    for query in _read_csv(V5_QUERIES_CSV):
        member_id = query["member_id"]
        claim = evidence.get(query["evidence_id"])
        if member_id not in documents or claim is None:
            continue
        rows.append(_row(query["query"], documents[member_id], documents[bandmate(member_id)]))
        artist = by_id[member_id]["artist"]
        rivals = [r for r in evidence_by_artist[artist] if r["member_id"] != member_id] or [
            r for r in evidence.values() if r["member_id"] != member_id
        ]
        rival = rng.choice(rivals)
        rows.append(
            _row(
                query["query"],
                evidence_text(by_id[member_id], claim),
                evidence_text(by_id[rival["member_id"]], rival),
            )
        )
    rng.shuffle(rows)
    return rows


def _row(anchor: str, positive: str, negative: str) -> dict[str, str]:
    return {"anchor": anchor, "positive": positive, "negative": negative}


def main() -> None:
    from datasets import Dataset
    from peft import LoraConfig, get_peft_model
    from sentence_transformers import SentenceTransformer, SentenceTransformerTrainer
    from sentence_transformers.sentence_transformer.losses import CachedGISTEmbedLoss
    from sentence_transformers.sentence_transformer.training_args import (
        BatchSamplers,
        SentenceTransformerTrainingArguments,
    )

    args = _parse_args()
    rows = build_rows(args.seed)
    dataset = Dataset.from_list(rows)
    print(f"{len(dataset)} training rows")

    # MPS's scaled_dot_product_attention cannot train with attention dropout.
    model = SentenceTransformer(BASE_MODEL, model_kwargs={"attn_implementation": "eager"})
    model.max_seq_length = MAX_SEQ_LENGTH
    model[0].model = get_peft_model(
        model[0].model,
        LoraConfig(
            r=LORA_RANK,
            lora_alpha=2 * LORA_RANK,
            lora_dropout=0.1,
            target_modules=LORA_TARGET_MODULES,
        ),
    )
    model[0].model.print_trainable_parameters()
    guide = SentenceTransformer(BASE_MODEL)
    guide.max_seq_length = MAX_SEQ_LENGTH
    loss = CachedGISTEmbedLoss(model, guide, mini_batch_size=args.mini_batch_size)

    training_args = SentenceTransformerTrainingArguments(
        output_dir=str(Path(args.output) / "checkpoints"),
        num_train_epochs=args.epochs,
        per_device_train_batch_size=args.batch_size,
        learning_rate=args.learning_rate,
        warmup_ratio=0.1,
        batch_sampler=BatchSamplers.NO_DUPLICATES,
        logging_steps=5,
        save_strategy="no",
        seed=args.seed,
        report_to="none",
    )
    trainer = SentenceTransformerTrainer(
        model=model, args=training_args, train_dataset=dataset, loss=loss
    )
    trainer.train()
    # Fold the adapters into the base weights so export sees a plain XLM-R model.
    model[0].model = model[0].model.merge_and_unload()
    model.save(args.output)
    print(f"Saved {args.output}")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--epochs", type=float, default=1)
    # Every row now carries two documents, so a smaller batch keeps NO_DUPLICATES
    # from running out of distinct member documents (154 in all).
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--mini-batch-size", type=int, default=8)
    parser.add_argument("--learning-rate", type=float, default=1e-4)
    parser.add_argument("--seed", type=int, default=20261028)
    return parser.parse_args()


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as file:
        return list(csv.DictReader(file))


if __name__ == "__main__":
    main()
