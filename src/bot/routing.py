from __future__ import annotations

from typing import TYPE_CHECKING

from src.bot.dispatcher import Dispatcher, Handler
from src.bot.features import menus
from src.bot.features.ai_curator import (
    is_ai_curator_entry_request,
    is_ai_curator_reason_followup,
)
from src.bot.features.artist_report import is_full_artist_report_request, report_artist
from src.bot.features.bias_radar import is_bias_radar_command
from src.bot.features.charts import is_historical_weekly_chart_request
from src.bot.features.daily_kpop import (
    daily_kpop_menu_reply,
    is_daily_kpop_category_request,
    is_daily_kpop_request,
)
from src.bot.features.fan_quiz import fan_attribute_quiz_reply, is_fan_attribute_quiz_request
from src.bot.features.member_quiz import is_member_quiz_answer, is_member_quiz_request
from src.bot.features.photo_card import is_photo_card_request
from src.bot.features.pocket import is_kpop_radar_request
from src.router import route_message

if TYPE_CHECKING:
    from src.bot.container import Features


def is_fixed_command(message: str) -> bool:
    """True for messages that name a fixed command, so free-text matchers must skip them."""
    return (
        menus.is_artist_picker_request(message)
        or is_kpop_radar_request(message)
        or menus.is_help_request(message)
        or menus.is_play_zone_request(message)
        or is_ai_curator_entry_request(message)
        or is_fan_attribute_quiz_request(message)
        or is_member_quiz_answer(message)
        or is_member_quiz_request(message)
        or is_daily_kpop_request(message)
        or is_daily_kpop_category_request(message)
        or is_photo_card_request(message)
        or is_historical_weekly_chart_request(message)
        or is_bias_radar_command(message)
        or route_message(message).name == "weekly_chart"
        or is_full_artist_report_request(message)
    )


def build_dispatcher(features: Features) -> Dispatcher:
    """Single routing table for every channel. Order matters: the first match wins."""
    ai_curator = features.ai_curator
    bias_radar = features.bias_radar
    member_quiz = features.member_quiz
    daily_kpop = features.daily_kpop
    charts = features.charts
    return Dispatcher(
        handlers=[
            Handler(
                "artist_picker",
                lambda c: menus.is_artist_picker_request(c.text),
                menus.artist_picker_reply,
            ),
            Handler(
                "kpop_pocket",
                lambda c: is_kpop_radar_request(c.text),
                features.pocket.kpop_radar_reply,
            ),
            Handler("help", lambda c: menus.is_help_request(c.text), menus.help_reply),
            Handler(
                "play_zone", lambda c: menus.is_play_zone_request(c.text), menus.play_zone_reply
            ),
            Handler(
                "ai_curator_entry",
                lambda c: is_ai_curator_entry_request(c.text),
                ai_curator.ai_curator_entry_reply,
            ),
            Handler(
                "ai_curator_preference",
                ai_curator.is_ai_curator_preference_message,
                ai_curator.ai_curator_preference_reply,
            ),
            Handler(
                "bias_radar_quiz",
                lambda c: bias_radar.is_bias_radar_quiz_request(c.text, c.user_id),
                bias_radar.bias_radar_reply,
            ),
            Handler(
                "fan_attribute_quiz",
                lambda c: is_fan_attribute_quiz_request(c.text),
                fan_attribute_quiz_reply,
            ),
            Handler(
                "member_quiz_answer",
                lambda c: is_member_quiz_answer(c.text),
                member_quiz.member_quiz_answer_reply,
            ),
            Handler(
                "member_quiz",
                lambda c: is_member_quiz_request(c.text),
                member_quiz.member_quiz_reply,
            ),
            Handler(
                "daily_kpop_menu",
                lambda c: is_daily_kpop_request(c.text),
                daily_kpop_menu_reply,
            ),
            Handler(
                "daily_kpop_category",
                lambda c: is_daily_kpop_category_request(c.text),
                daily_kpop.daily_kpop_category_reply,
            ),
            Handler(
                "photo_card",
                lambda c: is_photo_card_request(c.text),
                features.photo_card.photo_card_reply,
            ),
            Handler(
                "historical_weekly_chart",
                lambda c: is_historical_weekly_chart_request(c.text),
                charts.historical_weekly_chart_reply,
            ),
            Handler(
                "weekly_chart",
                lambda c: route_message(c.text).name == "weekly_chart",
                charts.weekly_chart_reply,
            ),
            Handler(
                "artist_report",
                lambda c: bool(report_artist(c)),
                features.artist_report.artist_report_reply,
            ),
            Handler(
                "ai_curator_reason",
                lambda c: is_ai_curator_reason_followup(c.text),
                ai_curator.ai_curator_reason_reply,
            ),
            # Last so every feature above gets the message first.
            Handler(
                "ai_curator_free_text",
                ai_curator.is_ai_curator_free_text_preference,
                ai_curator.ai_curator_preference_reply,
            ),
        ],
        fallback=Handler("fixed_command_help", lambda c: True, menus.fixed_command_help_reply),
    )
