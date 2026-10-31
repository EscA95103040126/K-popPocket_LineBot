from __future__ import annotations

import logging
import random
import re
import threading
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import quote

from flask import abort, request, send_file

from src.bot.dispatcher import MessageContext
from src.bot.reply import Reply

if TYPE_CHECKING:
    from src.bot.catalog import PlayZoneCatalog

logger = logging.getLogger(__name__)


MEMBER_QUIZ_EMPTY_TEXT = (
    "目前還沒有認人測驗題目，請先補 data/play_zone/member_quiz.csv，"
    "並把圖片放到 data/play_zone/member_quiz_images/"
)
MEMBER_QUIZ_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}


def _build_member_quiz_question_flex_contents(quiz: dict[str, str]) -> dict:
    return {
        "type": "bubble",
        "size": "mega",
        "hero": {
            "type": "image",
            "url": _member_quiz_image_url(quiz),
            "size": "full",
            "aspectRatio": "1:1",
            "aspectMode": "fit",
            "backgroundColor": "#F7FAF8",
        },
        "header": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": "#5D6F66",
            "paddingAll": "18px",
            "contents": [
                {
                    "type": "text",
                    "text": "認人測驗",
                    "size": "xs",
                    "color": "#E7F1EC",
                },
                {
                    "type": "text",
                    "text": quiz["question"],
                    "size": "xl",
                    "weight": "bold",
                    "color": "#FFFFFF",
                    "margin": "sm",
                    "wrap": True,
                },
            ],
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": "#F7FAF8",
            "paddingAll": "18px",
            "spacing": "md",
            "contents": [
                _member_quiz_option_button(quiz, "A", quiz["option_a"]),
                _member_quiz_option_button(quiz, "B", quiz["option_b"]),
            ],
        },
    }


def _member_quiz_option_button(quiz: dict[str, str], option: str, label: str) -> dict:
    return {
        "type": "button",
        "style": "primary",
        "height": "sm",
        "color": "#5D6F66",
        "action": {
            "type": "postback",
            "label": label,
            "data": f"認人答案:{quiz['id']}:{option}",
        },
    }


def _build_member_quiz_again_flex_contents() -> dict:
    return {
        "type": "bubble",
        "size": "kilo",
        "header": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": "#5D6F66",
            "paddingAll": "14px",
            "contents": [
                {
                    "type": "text",
                    "text": "再來一題？",
                    "size": "md",
                    "weight": "bold",
                    "color": "#FFFFFF",
                },
            ],
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": "#F7FAF8",
            "paddingAll": "14px",
            "spacing": "sm",
            "contents": [
                {
                    "type": "text",
                    "text": "想繼續挑戰認人測驗嗎？",
                    "size": "xs",
                    "color": "#3F5149",
                    "wrap": True,
                },
                {
                    "type": "button",
                    "style": "primary",
                    "height": "sm",
                    "color": "#5D6F66",
                    "action": {
                        "type": "message",
                        "label": "再一題",
                        "text": "認人測驗",
                    },
                },
                {
                    "type": "button",
                    "style": "secondary",
                    "height": "sm",
                    "action": {
                        "type": "message",
                        "label": "回 Play Zone",
                        "text": "互動專區",
                    },
                },
            ],
        },
    }


def is_member_quiz_request(message: str) -> bool:
    normalized = message.strip()
    return normalized in {"認人測驗", "再一題", "再來一題"}


def is_member_quiz_answer(message: str) -> bool:
    return re.fullmatch(r"認人答案:[^:]+:[AB]", message.strip()) is not None


def _member_quiz_answer_label(quiz: dict[str, str]) -> str:
    if quiz.get("answer") == "A":
        return quiz.get("option_a", "").strip()
    return quiz.get("option_b", "").strip()


def _parse_member_quiz_answer(message: str) -> tuple[str, str]:
    parts = message.strip().split(":")
    if len(parts) != 3 or parts[0] != "認人答案" or parts[2] not in {"A", "B"}:
        return "", ""
    return parts[1].strip(), parts[2]


def _normalize_member_quiz_row(row: dict[str, str]) -> dict[str, str]:
    return {
        "id": _normalize_csv_cell(row.get("id", "")),
        "question": _normalize_csv_cell(row.get("question", "")),
        "image_path": _normalize_csv_cell(row.get("image_path", "")),
        "option_a": _normalize_csv_cell(row.get("option_a", "")),
        "option_b": _normalize_csv_cell(row.get("option_b", "")),
        "answer": _normalize_csv_cell(row.get("answer", "")).upper(),
    }


def _normalize_csv_cell(value: str) -> str:
    return (value or "").replace("\u00a0", " ").strip()


def _member_quiz_row_is_usable(row: dict[str, str]) -> bool:
    normalized = _normalize_member_quiz_row(row)
    required_fields = ("id", "question", "image_path", "option_a", "option_b")
    return (
        all(normalized[field] for field in required_fields)
        and normalized["answer"] in {"A", "B"}
        and _member_quiz_filename_from_image_path(normalized["image_path"]) is not None
    )


def _member_quiz_source_key(
    rows: list[dict[str, str]],
) -> tuple[tuple[str, str, str, str, str, str], ...]:
    return tuple(
        (
            row.get("id", "").strip(),
            row.get("question", "").strip(),
            row.get("image_path", "").strip(),
            row.get("option_a", "").strip(),
            row.get("option_b", "").strip(),
            row.get("answer", "").strip(),
        )
        for row in rows
    )


def _member_quiz_image_url(quiz: dict[str, str]) -> str:
    filename = _member_quiz_filename_from_image_path(quiz.get("image_path", ""))
    if filename is None:
        filename = ""
    forwarded_host = request.headers.get("X-Forwarded-Host", "").split(",", 1)[0].strip()
    forwarded_proto = request.headers.get("X-Forwarded-Proto", "").split(",", 1)[0].strip()
    host = forwarded_host or request.host
    scheme = forwarded_proto or request.scheme
    if host.endswith(".hf.space"):
        return (
            "https://huggingface.co/spaces/EscA95103040126/kpop-agent/resolve/main/"
            f"data/play_zone/member_quiz_images/{quote(filename)}"
        )
    return f"{scheme}://{host}/play-zone/images/{quote(filename)}"


def _member_quiz_filename_from_image_path(image_path: str) -> str | None:
    normalized = image_path.strip().replace("\\", "/")
    filename = normalized.rsplit("/", 1)[-1]
    return safe_member_quiz_image_filename(filename)


def safe_member_quiz_image_filename(filename: str) -> str | None:
    normalized = filename.strip().replace("\\", "/")
    path = Path(normalized)
    if not normalized or "/" in normalized or path.name != normalized:
        return None
    if path.suffix.casefold() not in MEMBER_QUIZ_IMAGE_EXTENSIONS:
        return None
    return normalized


class MemberQuizFeature:
    """Guess-the-member quiz with a shuffled queue so questions do not repeat early."""

    def __init__(self, catalog: PlayZoneCatalog, rng: random.Random) -> None:
        self.catalog = catalog
        self.rng = rng
        self.member_quiz_queue: list[dict[str, str]] = []
        self.member_quiz_source_key: tuple[tuple[str, str, str, str, str, str], ...] = ()
        # gunicorn runs several threads; refill-then-pop must not interleave.
        self._queue_lock = threading.Lock()

    def member_quiz_answer_reply(self, context: MessageContext) -> Reply:
        response = self._member_quiz_answer_response(context.text)
        return Reply(
            report=response["report"],
            flex=response["flex"],
            alt_text="再來一題？",
            text_first=True,
        )

    def member_quiz_reply(self, context: MessageContext) -> Reply:
        response = self._member_quiz_question_response()
        return Reply(report=response["report"], flex=response["flex"], alt_text="認人測驗")

    def _member_quiz_question_response(self) -> dict:
        quiz = self._load_member_quiz_recommendation()
        if not quiz:
            return {"report": MEMBER_QUIZ_EMPTY_TEXT, "flex": None}
        return {
            "report": f"認人測驗：{quiz['question']}",
            "flex": _build_member_quiz_question_flex_contents(quiz),
        }

    def _member_quiz_answer_response(self, message: str) -> dict:
        quiz_id, selected_answer = _parse_member_quiz_answer(message)
        if not quiz_id or not selected_answer:
            return {"report": "這題資料已不存在，請重新抽一題。", "flex": None}

        quiz = self._find_member_quiz_row(quiz_id)
        if not quiz:
            return {
                "report": "這題資料已不存在，請重新抽一題。",
                "flex": None,
            }

        if selected_answer == quiz["answer"]:
            report = "答對了！"
        else:
            report = f"答錯了。正解是 {_member_quiz_answer_label(quiz)}。"
        return {"report": report, "flex": _build_member_quiz_again_flex_contents()}

    def _find_member_quiz_row(self, quiz_id: str) -> dict[str, str] | None:
        for row in self._load_member_quiz_rows():
            if row["id"] == quiz_id:
                return row
        return None

    def _load_member_quiz_recommendation(self) -> dict[str, str] | None:

        rows = self._load_member_quiz_rows()
        if not rows:
            self.member_quiz_queue = []
            self.member_quiz_source_key = ()
            return None

        source_key = _member_quiz_source_key(rows)
        with self._queue_lock:
            if not self.member_quiz_queue or self.member_quiz_source_key != source_key:
                self.member_quiz_queue = rows[:]
                self.rng.shuffle(self.member_quiz_queue)
                self.member_quiz_source_key = source_key
            return self.member_quiz_queue.pop()

    def _load_member_quiz_rows(self) -> list[dict[str, str]]:
        csv_path = self.catalog.base_dir / "data" / "play_zone" / "member_quiz.csv"
        return self.catalog.load_cached_csv_rows(
            csv_path,
            _member_quiz_row_is_usable,
            _normalize_member_quiz_row,
        )

    def member_quiz_image_dir(self) -> Path:
        return self.catalog.base_dir / "data" / "play_zone" / "member_quiz_images"

    def send_member_quiz_flex_image(self, filename: str):
        try:
            from PIL import Image, ImageOps

            source_path, cache_path = self._member_quiz_flex_image_cache_paths(filename)
            if not cache_path.exists():
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                with Image.open(source_path) as image:
                    source = ImageOps.exif_transpose(image).convert("RGB")
                    side = max(source.size)
                    canvas = Image.new("RGB", (side, side), color=(247, 250, 248))
                    offset = ((side - source.width) // 2, (side - source.height) // 2)
                    canvas.paste(source, offset)
                    canvas.save(cache_path, format="JPEG", quality=92, optimize=True)
        except Exception:
            logger.exception("Could not build member quiz Flex image: %s", filename)
            abort(404)

        return send_file(
            cache_path,
            mimetype="image/jpeg",
            download_name=f"{Path(filename).stem}_flex.jpg",
            max_age=60 * 60,
        )

    def _member_quiz_flex_image_cache_paths(self, filename: str) -> tuple[Path, Path]:
        source_path = self.member_quiz_image_dir() / filename
        stat = source_path.stat()
        cache_dir = self.catalog.base_dir / "data" / "cache" / "play_zone" / "flex"
        cache_name = f"{Path(filename).stem}-{stat.st_mtime_ns}-{stat.st_size}.jpg"
        return source_path, cache_dir / cache_name
