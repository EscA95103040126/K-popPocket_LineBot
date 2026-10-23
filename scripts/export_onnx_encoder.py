"""Build the int8 ONNX query encoder the bot ships for AI 入坑 v2.

The bot only needs to embed one short query per request, so it runs BAAI/bge-m3
through onnxruntime instead of torch. This script downloads the official ONNX export
of bge-m3, applies dynamic int8 quantization (MatMul and the 250k-row embedding
Gather, which alone is ~1GB in fp32) and writes model.onnx + tokenizer.json.

Usage:
    python scripts/export_onnx_encoder.py                 # writes models/bge-m3-int8/
    python scripts/export_onnx_encoder.py --out some/dir

Needs the `curator` dependency group (huggingface_hub, onnx, onnxruntime).
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.bot.semantic_index import ONNX_ENCODER_DIR

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
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as download_dir:
        # local_dir keeps model.onnx next to its external data; the hub cache's
        # symlinked blobs fail onnxruntime's external-data path check.
        for filename in SOURCE_FILES:
            hf_hub_download(SOURCE_REPO, filename, local_dir=download_dir)
        source = Path(download_dir) / "onnx"
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


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=str(PROJECT_ROOT / ONNX_ENCODER_DIR))
    return parser.parse_args()


if __name__ == "__main__":
    main()
