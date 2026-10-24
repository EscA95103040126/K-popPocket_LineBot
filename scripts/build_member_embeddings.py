"""Precompute AI 入坑 member embeddings with the shipped int8 encoder.

Encoding the 154 member documents takes about a minute on two CPU cores, too slow
for bot startup, so it happens here, locally, before models/ is committed to the
Space. Rerun after changing anything under data/curator/; the bot falls back to v1
while the stored digest does not match the current documents.

Usage:
    python scripts/train_encoder.py            # once, then export it:
    python scripts/export_onnx_encoder.py --source models/bge-m3-curator-v3
    python scripts/build_member_embeddings.py
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.bot.catalog import PlayZoneCatalog
from src.bot.semantic_index import ONNX_ENCODER_DIR, OnnxEncoder, write_member_embeddings


def main() -> None:
    model_dir = PROJECT_ROOT / ONNX_ENCODER_DIR
    if not (model_dir / "model.onnx").exists():
        raise SystemExit(f"{model_dir}/model.onnx missing; see this script's usage")
    members = PlayZoneCatalog(PROJECT_ROOT).load_bias_radar_members()
    print(f"Encoding {len(members)} member documents...", flush=True)
    path = write_member_embeddings(PROJECT_ROOT, members, OnnxEncoder(model_dir))
    print(f"Wrote {path}")


if __name__ == "__main__":
    main()
