from __future__ import annotations

import logging
import random
from typing import TYPE_CHECKING

from src.bot.catalog import daily_kpop_csv_label
from src.bot.dispatcher import MessageContext
from src.bot.flex_common import (
    build_daily_kpop_redraw_flex_contents,
    selection_page_flex_contents,
)
from src.bot.reply import Reply

if TYPE_CHECKING:
    from src.bot.catalog import PlayZoneCatalog
    from src.bot.features.pocket import PocketFeature
    from src.tools.kpop_radar import KpopRadarRepository

logger = logging.getLogger(__name__)


def _build_daily_kpop_flex_contents() -> dict:
    return selection_page_flex_contents(
        title="每日一首 K-pop",
        subtitle="今天想看哪一種？",
        description="每日推薦資料分成 MV、直拍、經典舞台三份 CSV，方便直接補歌名與連結。",
        accent_color="#4E779A",
        body_background="#F4F8FC",
        subtitle_color="#EAF3FF",
        description_color="#314B60",
        item_description_color="#48677E",
        items=[
            {
                "icon": "🎬",
                "title": "MV",
                "description": "官方 MV 或值得補的主打歌。",
                "text": "每日 MV",
            },
            {
                "icon": "🎥",
                "title": "直拍",
                "description": "舞台表現、成員魅力與飯拍導向。",
                "text": "每日直拍",
            },
            {
                "icon": "🏆",
                "title": "經典舞台",
                "description": "回顧代表性舞台與名場面。",
                "text": "每日經典舞台",
            },
        ],
    )


def is_daily_kpop_request(message: str) -> bool:
    normalized = message.strip().casefold()
    return normalized in {
        "每日一首",
        "每日一首 k-pop",
        "每日一首 kpop",
        "今日推歌",
        "每日 k-pop",
        "每日 kpop",
    }


def is_daily_kpop_category_request(message: str) -> bool:
    normalized = message.strip()
    return normalized in {"每日 MV", "每日MV", "每日直拍", "每日 經典舞台", "每日經典舞台"}


def daily_kpop_menu_reply(context: MessageContext) -> Reply:
    return Reply(
        report="每日一首 K-pop",
        flex=_build_daily_kpop_flex_contents(),
        alt_text="每日一首 K-pop",
        fallback_text="請選擇：每日 MV、每日直拍、每日經典舞台",
    )


def _daily_kpop_category(message: str) -> str:
    normalized = message.strip().replace(" ", "")
    if "直拍" in normalized:
        return "直拍"
    if "經典舞台" in normalized:
        return "經典舞台"
    return "MV"


def _daily_kpop_item_type(category: str) -> str:
    if category == "直拍":
        return "fancam"
    if category == "MV":
        return "mv"
    return ""


def _daily_kpop_redraw_text(category: str) -> str:
    if category == "直拍":
        return "每日直拍"
    if category == "經典舞台":
        return "每日 經典舞台"
    return "每日 MV"


def _daily_kpop_source_key(rows: list[dict[str, str]]) -> tuple[tuple[str, str, str, str], ...]:
    return tuple(
        (
            row.get("artist", "").strip(),
            row.get("title", "").strip(),
            row.get("member", "").strip(),
            row.get("url", "").strip(),
        )
        for row in rows
    )


def _format_daily_kpop_recommendation(category: str, recommendation: dict[str, str]) -> str:
    artist = recommendation.get("artist", "").strip()
    title = recommendation.get("title", "").strip()
    url = recommendation.get("url", "").strip()
    member = recommendation.get("member", "").strip()

    lines = [f"🎵 今日推薦 {category}", f"今天推薦的是 {artist} 的《{title}》。"]
    if category == "直拍" and member:
        lines.append(f"直拍成員：{member}")
    lines.append(url)
    return "\n".join(lines)


def _format_kpop_item_recommendation(category: str, recommendation: dict[str, object]) -> str:
    artist = str(recommendation.get("artist") or "").strip()
    title = str(recommendation.get("title") or "").strip()
    url = str(recommendation.get("url") or "").strip()
    member = str(recommendation.get("member") or "").strip()

    lines = [f"🎵 今日推薦 {category}", f"今天推薦的是 {artist} 的《{title}》。"]
    if member:
        lines.append(f"成員：{member}")
    if url:
        lines.append(url)
    return "\n".join(lines)


class DailyKpopFeature:
    """Daily MV / fancam / stage draws; MV draws are personalised when Supabase is on."""

    def __init__(
        self,
        catalog: PlayZoneCatalog,
        radar_repo: KpopRadarRepository,
        pocket: PocketFeature,
        rng: random.Random,
    ) -> None:
        self.catalog = catalog
        self.radar_repo = radar_repo
        self.pocket = pocket
        self.rng = rng
        self.daily_kpop_queues: dict[str, list[dict[str, str]]] = {}
        self.daily_kpop_source_keys: dict[str, tuple[tuple[str, str, str, str], ...]] = {}

    def daily_kpop_category_reply(self, context: MessageContext) -> Reply:
        response = self._daily_kpop_response(context.text, user_id=context.user_id)
        return Reply(
            report=response["report"],
            flex=response["flex"],
            alt_text="再抽一首 K-pop",
            text_first=True,
        )

    def _daily_kpop_response(self, message: str, user_id: str = "analyze-user") -> dict:
        category = _daily_kpop_category(message)
        if category == "MV" and self.radar_repo.enabled:
            try:
                recommendation = self.radar_repo.recommend_daily_mv(user_id)
            except Exception:
                logger.exception("Supabase daily MV recommendation failed; using CSV fallback.")
            else:
                if recommendation:
                    return {
                        "report": _format_kpop_item_recommendation(category, recommendation),
                        "flex": build_daily_kpop_redraw_flex_contents(
                            save_item_id=str(recommendation.get("id") or "")
                        ),
                    }
                return {
                    "report": "目前 Supabase 還沒有可推薦的 MV，請先匯入 kpop_items。",
                    "flex": build_daily_kpop_redraw_flex_contents(),
                }

        recommendation = self._load_daily_kpop_recommendation(category)
        if recommendation:
            return {
                "report": _format_daily_kpop_recommendation(category, recommendation),
                "flex": self.pocket.build_recommendation_action_flex_contents(
                    item_type=_daily_kpop_item_type(category),
                    url=recommendation.get("url", ""),
                    redraw_label=f"再抽{category}",
                    redraw_text=_daily_kpop_redraw_text(category),
                    daily_redraw=True,
                    fallback_flex=build_daily_kpop_redraw_flex_contents(),
                ),
            }
        return {
            "report": (
                f"每日一首 K-pop：{category}\n"
                f"入口已建立。請先在 {daily_kpop_csv_label(category)} 補上歌曲標題與連結。"
            ),
            "flex": build_daily_kpop_redraw_flex_contents(),
        }

    def _load_daily_kpop_recommendation(self, category: str) -> dict[str, str] | None:
        rows = self.catalog.load_daily_kpop_rows(category)
        if not rows:
            return None

        source_key = _daily_kpop_source_key(rows)
        queue = self.daily_kpop_queues.get(category, [])
        if not queue or self.daily_kpop_source_keys.get(category) != source_key:
            queue = rows[:]
            self.rng.shuffle(queue)
            self.daily_kpop_queues[category] = queue
            self.daily_kpop_source_keys[category] = source_key
        return self.daily_kpop_queues[category].pop()
