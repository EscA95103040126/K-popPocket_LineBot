"""Build the int8 ONNX encoders for AI 入坑.

The bot only needs to embed one short query per request, so it runs BAAI/bge-m3
through onnxruntime instead of torch. This script downloads the official ONNX export
of bge-m3, applies dynamic int8 quantization (MatMul and the 250k-row embedding
Gather, which alone is ~1GB in fp32) and writes model.onnx + tokenizer.json.

With --source it exports a locally fine-tuned SentenceTransformer (v3, see
scripts/train_encoder.py) through torch instead, with the same CLS + L2-normalize
`sentence_embedding` output the bot expects, then quantizes it the same way. The bot
ships the v3 export (models/bge-m3-v3-int8/, see src/bot/semantic_index.py).

Usage:
    python scripts/export_onnx_encoder.py                 # writes models/bge-m3-int8/
    python scripts/export_onnx_encoder.py --out some/dir
    python scripts/export_onnx_encoder.py --source models/bge-m3-curator-v3 \
        --out models/bge-m3-v3-int8

Needs the `encoder-build` dependency group (huggingface_hub, onnx); --source also
needs `curator` (torch, sentence-transformers).
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.bot.semantic_index import OFFICIAL_ONNX_DIR, ONNX_ENCODER_DIR

SOURCE_REPO = "BAAI/bge-m3"
SOURCE_FILES = (
    "onnx/model.onnx",
    "onnx/model.onnx_data",
    "onnx/Constant_7_attr__value",
    "onnx/tokenizer.json",
)


def main() -> None:
    from huggingface_hub import hf_hub_download
    from onnxruntime.quantization import QuantType, quantize_dynamic

    args = _parse_args()
    out_dir = Path(
        args.out or PROJECT_ROOT / (ONNX_ENCODER_DIR if args.source else OFFICIAL_ONNX_DIR)
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as work_dir:
        if args.source:
            source = Path(work_dir)
            _export_local_model(Path(args.source), source)
        else:
            # local_dir keeps model.onnx next to its external data; the hub cache's
            # symlinked blobs fail onnxruntime's external-data path check.
            for filename in SOURCE_FILES:
                hf_hub_download(SOURCE_REPO, filename, local_dir=work_dir)
            source = Path(work_dir) / "onnx"
        print("Quantizing (takes a few minutes)...", flush=True)
        quantize_dynamic(
            source / "model.onnx",
            out_dir / "model.onnx",
            op_types_to_quantize=["MatMul", "Gather"],
            weight_type=QuantType.QInt8,
        )
        shutil.copy(source / "tokenizer.json", out_dir / "tokenizer.json")
    size_mb = (out_dir / "model.onnx").stat().st_size / 1e6
    print(f"Wrote {out_dir}/model.onnx ({size_mb:.0f} MB) and tokenizer.json")


def _export_local_model(source: Path, work_dir: Path) -> None:
    import torch
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(str(source), device="cpu")
    transformer = model[0].auto_model.eval()

    class DenseEncoder(torch.nn.Module):
        # bge-m3's dense embedding: the CLS token, L2-normalized.
        def __init__(self) -> None:
            super().__init__()
            self.transformer = transformer

        def forward(self, input_ids, attention_mask):
            hidden = self.transformer(input_ids=input_ids, attention_mask=attention_mask)
            return torch.nn.functional.normalize(hidden.last_hidden_state[:, 0], dim=-1)

    dummy = torch.ones((1, 8), dtype=torch.long)
    print(f"Exporting {source} to ONNX...", flush=True)
    torch.onnx.export(
        DenseEncoder(),
        (dummy, torch.ones_like(dummy)),
        str(work_dir / "model.onnx"),
        input_names=["input_ids", "attention_mask"],
        output_names=["sentence_embedding"],
        dynamic_axes={
            "input_ids": {0: "batch_size", 1: "sequence_length"},
            "attention_mask": {0: "batch_size", 1: "sequence_length"},
            "sentence_embedding": {0: "batch_size"},
        },
        opset_version=17,
        dynamo=False,
    )
    shutil.copy(source / "tokenizer.json", work_dir / "tokenizer.json")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", help="local SentenceTransformer dir to export")
    parser.add_argument("--out", help="defaults to the shipped dir with --source, else v2's")
    return parser.parse_args()


if __name__ == "__main__":
    main()
