"""AI 入坑 v5：把成員照片算成影像向量，回答「長得像某人」。

照片清單是 Grok 的 appearance 批次（photo_manifest.csv，只收 face_visible=yes），照片
先下載到 staging（不進 git），這裡先用 YuNet 切出臉（整張照片的向量主要反映造型和
拍攝場合，同性別成員彼此都在 0.91 上下），再用 CLIP 算出每張的向量，每位成員取平均。偵測
不到臉的照片不用。

平均後不再正規化：兩位成員平均向量的內積，等於兩人照片兩兩相似度的平均，不受照片
張數影響。正規化後照片多的人雜訊互相抵銷，跟所有人都比較像（張數和對其他人的平均
相似度相關 0.46），會在「長得像」排序裡占便宜。
repo 和 Space 只放平均向量（data/curator/member_photo_embeddings.npz），Bot 執行時只需要
numpy，不用載入 CLIP。

照片不足 MIN_PHOTOS 張的成員不寫入，避免一兩張特殊造型代表整個人。

YuNet 模型（OpenCV model zoo）放在 models/yunet/：
    https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx

Usage:
    uv run --group curator python scripts/build_photo_embeddings.py \\
        --photos data/curator/staging/photos_v3
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import sys
from collections import defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.bot.catalog import PlayZoneCatalog
from src.bot.photo_similarity import MEMBER_PHOTO_EMBEDDINGS_PATH, MIN_PHOTOS

MANIFEST = PROJECT_ROOT / "data/curator/staging/grok/appearance_v5/photo_manifest.csv"
CLIP_MODEL = "clip-ViT-B-32"
YUNET_MODEL = PROJECT_ROOT / "models/yunet/face_detection_yunet_2023mar.onnx"
FACE_SCORE = 0.8
# 臉框往外擴，保留髮型和臉型輪廓；粉絲說的「貓系」「小狗相」不只看五官。
FACE_MARGIN = 0.6


def photo_path(photos: Path, row: dict[str, str]) -> Path:
    """下載時的檔名：成員 ID 加網址雜湊，同一張圖重跑不會重抓。"""

    digest = hashlib.sha1(row["image_url"].encode()).hexdigest()[:16]
    return photos / f"{row['member_id']}__{digest}"


def crop_face(image, detector):
    """最大那張臉往外擴的區域；沒有夠清楚的臉就回傳 None。"""

    import numpy

    rgb = numpy.asarray(image)
    bgr = numpy.ascontiguousarray(rgb[:, :, ::-1])
    height, width = bgr.shape[:2]
    detector.setInputSize((width, height))
    _, faces = detector.detect(bgr)
    if faces is None:
        return None
    faces = [face for face in faces if face[-1] >= FACE_SCORE]
    if not faces:
        return None
    x, y, w, h = max(faces, key=lambda face: face[2] * face[3])[:4]
    side = max(w, h) * (1 + 2 * FACE_MARGIN)
    cx, cy = x + w / 2, y + h / 2
    box = (
        max(0, int(cx - side / 2)),
        max(0, int(cy - side / 2)),
        min(width, int(cx + side / 2)),
        min(height, int(cy + side / 2)),
    )
    return image.crop(box)


def main() -> None:
    import cv2
    import numpy
    from PIL import Image
    from sentence_transformers import SentenceTransformer

    args = _parse_args()
    member_ids = {m["id"] for m in PlayZoneCatalog(PROJECT_ROOT).load_bias_radar_members()}
    with Path(args.manifest).open(encoding="utf-8", newline="") as file:
        rows = [r for r in csv.DictReader(file) if r["face_visible"] == "yes"]
    paths: dict[str, list[Path]] = defaultdict(list)
    for row in rows:
        path = photo_path(Path(args.photos), row)
        if row["member_id"] in member_ids and path.exists():
            paths[row["member_id"]].append(path)

    model = SentenceTransformer(CLIP_MODEL)
    detector = cv2.FaceDetectorYN.create(str(YUNET_MODEL), "", (320, 320), FACE_SCORE)
    kept, vectors, counts, skipped = [], [], [], []
    no_face = 0
    for member_id in sorted(paths):
        images = []
        for path in paths[member_id]:
            try:
                with Image.open(path) as image:
                    face = crop_face(image.convert("RGB"), detector)
            except OSError:
                print(f"讀不到 {path.name}")
                continue
            if face is None:
                no_face += 1
            else:
                images.append(face)
        if len(images) < MIN_PHOTOS:
            skipped.append(f"{member_id}({len(images)})")
            continue
        embeddings = model.encode(images, normalize_embeddings=True, convert_to_numpy=True)
        kept.append(member_id)
        vectors.append(embeddings.mean(axis=0))
        counts.append(len(images))
    output = PROJECT_ROOT / MEMBER_PHOTO_EMBEDDINGS_PATH
    numpy.savez(
        output,
        member_ids=numpy.array(kept),
        embeddings=numpy.array(vectors, dtype=numpy.float32),
        photo_counts=numpy.array(counts),
        model=numpy.array(CLIP_MODEL),
    )
    missing = sorted(member_ids - set(kept))
    print(f"寫入 {len(kept)}/{len(member_ids)} 位成員到 {output}（{no_face} 張偵測不到臉）")
    print(f"照片不足 {MIN_PHOTOS} 張：{', '.join(skipped) or '無'}")
    print(f"沒有照片：{', '.join(m for m in missing if m not in paths) or '無'}")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", default=str(MANIFEST))
    parser.add_argument("--photos", default=str(PROJECT_ROOT / "data/curator/staging/photos_v3"))
    return parser.parse_args()


if __name__ == "__main__":
    main()
