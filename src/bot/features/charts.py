from __future__ import annotations

import re
from datetime import date, timedelta
from typing import TYPE_CHECKING

from src.bot.dispatcher import MessageContext
from src.bot.reply import QuickReplyAction, Reply

if TYPE_CHECKING:
    from src.agent import KpopAnalysisAgent


HISTORICAL_WEEKLY_CHART_PREFIX = "歷史週榜:"


def is_historical_weekly_chart_request(message: str) -> bool:
    return _historical_weekly_chart_date(message) != ""


def _historical_weekly_chart_date(message: str) -> str:
    normalized = message.strip()
    if not normalized.startswith(HISTORICAL_WEEKLY_CHART_PREFIX):
        return ""
    raw_date = normalized.removeprefix(HISTORICAL_WEEKLY_CHART_PREFIX).strip()
    return _normalize_weekly_chart_date(raw_date)


def _normalize_weekly_chart_date(raw_date: str) -> str:
    compact = re.sub(r"\D+", "", raw_date)
    if len(compact) != 8:
        return ""
    return f"{compact[:4]}-{compact[4:6]}-{compact[6:]}"


def _weekly_chart_date_label(chart_date: str) -> str:
    try:
        start_date = date.fromisoformat(chart_date)
    except ValueError:
        return chart_date
    end_date = start_date + timedelta(days=6)
    return f"{start_date.month}/{start_date.day}-{end_date.month}/{end_date.day}"


class ChartFeature:
    """Weekly Bugs chart and its history, served from the analysis agent's cache."""

    def __init__(self, agent: KpopAnalysisAgent) -> None:
        self.agent = agent

    def build_weekly_chart_history_quick_reply(
        self,
        current_chart_date: str = "",
        limit: int = 12,
    ) -> tuple[QuickReplyAction, ...]:
        chart_dates = [
            chart_date
            for chart_date in self.agent.list_weekly_chart_dates(limit=limit + 1, min_items=1)
            if chart_date and chart_date != current_chart_date
        ][:limit]
        return tuple(
            QuickReplyAction(
                label=f"📅 {_weekly_chart_date_label(chart_date)}",
                text=f"{HISTORICAL_WEEKLY_CHART_PREFIX}{chart_date}",
            )
            for chart_date in reversed(chart_dates)
        )

    def historical_weekly_chart_reply(self, context: MessageContext) -> Reply:
        chart_date = _historical_weekly_chart_date(context.text)
        return Reply(
            report=self.agent.generate_weekly_chart_report_for_date(chart_date),
            cache={"type": "weekly_chart_history", "chart_date": chart_date},
        )

    def weekly_chart_reply(self, context: MessageContext) -> Reply:
        chart_cache = self.agent.get_weekly_chart_cache()
        return Reply(
            report=chart_cache["report"],
            quick_replies=self.build_weekly_chart_history_quick_reply(
                current_chart_date=chart_cache.get("chart", {}).get("chart_date", ""),
            ),
            cache={"type": "weekly_chart", "cached_at": chart_cache["cached_at"]},
        )
