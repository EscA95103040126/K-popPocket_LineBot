"""AI 入坑 v5：成員照片向量，用來回答「長得像某人」。

向量由 scripts/build_photo_embeddings.py 在本機用 CLIP 算好：每位成員多張照片的單位向量
取平均、不再正規化，內積就是兩人照片兩兩相似度的平均。Bot 執行時只做內積，不載入影像
模型。照片不足的成員沒有向量，相似度當作中性。
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

MEMBER_PHOTO_EMBEDDINGS_PATH = Path("data") / "curator" / "member_photo_embeddings.npz"
# 一兩張照片容易被單次造型帶偏，至少 3 張才寫入向量。
MIN_PHOTOS = 3


class PhotoSimilarity:
    def __init__(self, member_ids: list[str], embeddings) -> None:
        self.position = {member_id: i for i, member_id in enumerate(member_ids)}
        self.member_ids = member_ids
        self.embeddings = embeddings

    @classmethod
    def load(cls, base_dir: Path) -> PhotoSimilarity | None:
        path = base_dir / MEMBER_PHOTO_EMBEDDINGS_PATH
        if not path.exists():
            logger.info("No member photo embeddings at %s; looks use text only.", path)
            return None
        try:
            import numpy

            stored = numpy.load(path)
            return cls([str(i) for i in stored["member_ids"]], stored["embeddings"])
        except Exception:
            logger.exception("Could not load member photo embeddings.")
            return None

    def scores(self, reference_ids) -> dict[str, float]:
        """每位有照片的成員和參照成員照片兩兩的平均餘弦相似度；參照成員都沒照片時是空的。"""

        rows = [self.position[i] for i in reference_ids if i in self.position]
        if not rows:
            return {}
        similarities = (self.embeddings @ self.embeddings[rows].T).mean(axis=1)
        return {
            member_id: float(score)
            for member_id, score in zip(self.member_ids, similarities, strict=True)
        }
