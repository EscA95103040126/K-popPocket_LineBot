from __future__ import annotations

import random
from typing import TYPE_CHECKING

from src.bot.dispatcher import MessageContext
from src.bot.flex_common import (
    PLAY_ZONE_ACCENT_COLOR,
    PLAY_ZONE_BODY_COLOR,
    PLAY_ZONE_TEXT_COLOR,
)
from src.bot.reply import Reply

if TYPE_CHECKING:
    from src.bot.catalog import PlayZoneCatalog
    from src.bot.features.pocket import PocketFeature


PHOTO_CARD_EMPTY_TEXT = "目前還沒有神圖資料，請先補 data/play_zone/photo_cards.csv"


def _build_photo_card_redraw_flex_contents() -> dict:
    return {
        "type": "bubble",
        "size": "kilo",
        "header": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": PLAY_ZONE_ACCENT_COLOR,
            "paddingAll": "14px",
            "contents": [
                {
                    "type": "text",
                    "text": "再抽一次",
                    "size": "md",
                    "weight": "bold",
                    "color": "#FFFFFF",
                },
            ],
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": PLAY_ZONE_BODY_COLOR,
            "paddingAll": "14px",
            "spacing": "sm",
            "contents": [
                {
                    "type": "text",
                    "text": "想再抽一張神圖嗎？",
                    "size": "xs",
                    "color": PLAY_ZONE_TEXT_COLOR,
                    "wrap": True,
                },
                {
                    "type": "button",
                    "style": "primary",
                    "height": "sm",
                    "color": PLAY_ZONE_ACCENT_COLOR,
                    "action": {
                        "type": "message",
                        "label": "再抽一次",
                        "text": "神圖抽卡",
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


def is_photo_card_request(message: str) -> bool:
    normalized = message.strip()
    return normalized in {"神圖抽卡", "再抽一次神圖", "再抽一張", "抽卡"}


def _photo_card_row_is_usable(row: dict[str, str]) -> bool:
    return bool(
        row.get("artist", "").strip()
        and row.get("type", "").strip()
        and row.get("url", "").strip()
    )


def _photo_card_source_key(rows: list[dict[str, str]]) -> tuple[tuple[str, str, str], ...]:
    return tuple(
        (
            row.get("artist", "").strip(),
            row.get("type", "").strip(),
            row.get("url", "").strip(),
        )
        for row in rows
    )


def _format_photo_card_recommendation(card: dict[str, str]) -> str:
    artist = card.get("artist", "").strip()
    card_type = card.get("type", "").strip()
    url = card.get("url", "").strip()
    return "\n".join(
        [
            "✨ 神圖抽卡結果 ✨",
            "",
            "🎉 恭喜你今天抽到",
            f"💖 {artist}",
            f"📸 類型：{card_type}",
            "",
            "🔗 點開看神圖",
            url,
        ]
    )


class PhotoCardFeature:
    """Photo card draws from photo_cards.csv with a shuffled queue."""

    def __init__(
        self,
        catalog: PlayZoneCatalog,
        pocket: PocketFeature,
        rng: random.Random,
    ) -> None:
        self.catalog = catalog
        self.pocket = pocket
        self.rng = rng
        self.photo_card_queue: list[dict[str, str]] = []
        self.photo_card_source_key: tuple[tuple[str, str, str], ...] = ()

    def photo_card_reply(self, context: MessageContext) -> Reply:
        response = self._photo_card_response()
        return Reply(
            report=response["report"],
            flex=response["flex"],
            alt_text="再抽一次",
            text_first=True,
        )

    def _photo_card_response(self) -> dict:
        card = self._load_photo_card_recommendation()
        if not card:
            return {"report": PHOTO_CARD_EMPTY_TEXT, "flex": None}
        return {
            "report": _format_photo_card_recommendation(card),
            "flex": self.pocket.build_recommendation_action_flex_contents(
                item_type="photo",
                url=card.get("url", ""),
                redraw_label="再抽神圖",
                redraw_text="神圖抽卡",
                fallback_flex=_build_photo_card_redraw_flex_contents(),
            ),
        }

    def _load_photo_card_recommendation(self) -> dict[str, str] | None:

        rows = self._load_photo_card_rows()
        if not rows:
            self.photo_card_queue = []
            self.photo_card_source_key = ()
            return None

        source_key = _photo_card_source_key(rows)
        if not self.photo_card_queue or self.photo_card_source_key != source_key:
            self.photo_card_queue = rows[:]
            self.rng.shuffle(self.photo_card_queue)
            self.photo_card_source_key = source_key
        return self.photo_card_queue.pop()

    def _load_photo_card_rows(self) -> list[dict[str, str]]:
        csv_path = self.catalog.base_dir / "data" / "play_zone" / "photo_cards.csv"
        return self.catalog.load_cached_csv_rows(csv_path, _photo_card_row_is_usable)
