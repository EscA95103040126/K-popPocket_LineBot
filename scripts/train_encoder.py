"""Fine-tune bge-m3 on synthetic fan queries for AI 入坑 v3.

Pairs each query from data/curator/synthetic_queries.csv with its member's retrieval
document and trains with CachedGISTEmbedLoss: in-batch negatives as usual, but the
frozen base model acts as a guide and drops negatives it scores above the positive.
Queries like 「甜甜的女生」 fit several members, so plain in-batch negatives would punish
the model for matching them. NO_DUPLICATES keeps two copies of one member document out
of the same batch.

Training is LoRA (rank-16 adapters on the attention projections, merged back before
saving). Full fine-tuning of all 568M parameters needed far more than the M1 Pro's
32GB: AdamW state for the 250k-row embedding table alone is ~2GB, and the run spent
hours in swap.

Usage (needs the `curator` dependency group; runs on Apple Silicon MPS):
    uv run --group curator python scripts/train_encoder.py
    uv run --group curator python scripts/export_onnx_encoder.py \\
        --source models/bge-m3-curator-v3   # writes models/bge-m3-v3-int8/
"""

from __future__ import annotations

import argparse
import csv
import random
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.bot.catalog import PlayZoneCatalog
from src.bot.semantic_index import load_member_documents

SYNTHETIC_QUERIES_CSV = PROJECT_ROOT / "data" / "curator" / "synthetic_queries.csv"
BASE_MODEL = "BAAI/bge-m3"
DEFAULT_OUTPUT = PROJECT_ROOT / "models" / "bge-m3-curator-v3"
# Member documents run 252-337 tokens; queries are far shorter.
MAX_SEQ_LENGTH = 384
LORA_RANK = 16
LORA_TARGET_MODULES = ["query", "key", "value"]


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
    members = PlayZoneCatalog(PROJECT_ROOT).load_bias_radar_members()
    documents = load_member_documents(PROJECT_ROOT, members)
    with SYNTHETIC_QUERIES_CSV.open(encoding="utf-8", newline="") as file:
        rows = [row for row in csv.DictReader(file) if row["member_id"] in documents]
    random.Random(args.seed).shuffle(rows)
    dataset = Dataset.from_dict(
        {
            "anchor": [row["query"] for row in rows],
            "positive": [documents[row["member_id"]] for row in rows],
        }
    )
    print(f"{len(dataset)} training pairs over {len({r['member_id'] for r in rows})} members")

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
    parser.add_argument("--epochs", type=float, default=2)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--mini-batch-size", type=int, default=8)
    parser.add_argument("--learning-rate", type=float, default=1e-4)
    parser.add_argument("--seed", type=int, default=20261024)
    return parser.parse_args()


if __name__ == "__main__":
    main()
