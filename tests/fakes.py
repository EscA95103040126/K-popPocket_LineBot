"""Shared test doubles and app builders. Tests build their own app via make_app()."""

from __future__ import annotations

import dataclasses
import itertools
import random
from collections.abc import Callable
from contextlib import contextmanager
from pathlib import Path
from time import time

from flask import Flask

from src.agent import KpopAnalysisAgent
from src.bot.container import BotDeps
from src.bot.line_events import LineEventGuard
from src.bot.llm import GeminiTextClient
from src.config import Settings
from src.tools.kpop_radar import KpopRadarRepository
from src.web.app_factory import create_app

REPO_ROOT = Path(__file__).resolve().parents[1]
SAVED_ITEM_ID = "00000000-0000-0000-0000-000000000001"


class FakeSaveResult:
    def __init__(self, status: str) -> None:
        self.status = status

    @property
    def saved(self) -> bool:
        return self.status == "saved"

    @property
    def duplicate(self) -> bool:
        return self.status == "duplicate"


class FakeRadarRepository:
    enabled = True

    def __init__(self) -> None:
        self.preference = "all"
        self.saved_item_ids: list[str] = []
        self.item = {
            "id": SAVED_ITEM_ID,
            "item_type": "mv",
            "gender_category": "girl_group",
            "artist": "NMIXX",
            "member": "",
            "title": "DASH",
            "url": "https://example.com/nmixx-dash",
        }

    def status(self) -> dict:
        return {"ok": True}

    def ensure_user(self, line_user_id: str) -> None:
        pass

    def get_preference(self, line_user_id: str) -> str:
        return self.preference

    def upsert_preference(self, line_user_id: str, preferred_gender: str) -> str:
        self.preference = preferred_gender
        return preferred_gender

    def saved_counts(self, line_user_id: str) -> dict[str, int]:
        return {"mv": len(self.saved_item_ids), "fancam": 0, "photo": 0}

    def list_saved_items(self, line_user_id: str, item_type: str) -> list[dict[str, str]]:
        if item_type == "mv" and self.saved_item_ids:
            return [self.item]
        return []

    def save_item(self, line_user_id: str, item_id: str) -> FakeSaveResult:
        if item_id in self.saved_item_ids:
            return FakeSaveResult("duplicate")
        self.saved_item_ids.append(item_id)
        return FakeSaveResult("saved")

    def recommend_daily_mv(self, line_user_id: str) -> dict[str, str]:
        return self.item

    def find_item_by_url(self, item_type: str, url: str) -> dict[str, str] | None:
        if item_type == "mv" and url == self.item["url"]:
            return self.item
        return None


class FakeAgent:
    def get_weekly_chart_cache(self) -> dict:
        return {
            "report": "# 本週 K-pop 榜單\n1. Fake Song - Fake Artist",
            "cached_at": "2026-10-20T00:00:00+00:00",
            "chart": {"chart_date": "2026-10-12"},
        }

    def generate_weekly_chart_report_for_date(self, chart_date: str) -> str:
        return f"# Bugs 歷史週榜\n榜單日期：{chart_date}\n1. Old Song - Old Artist"

    def list_weekly_chart_dates(self, limit: int = 12, min_items: int = 1) -> list[str]:
        return ["2026-10-12", "2026-10-05", "2026-09-28"][:limit]

    def get_artist_analysis_cache(self, artist: str, period_months: int = 3) -> dict:
        return {
            "report": f"# {artist} 近期市場與輿論分析\n期間：{period_months} 個月",
            "artist": artist,
            "cached_at": "2026-10-11T00:00:00+00:00",
            "cache_type": "absa",
            "flex": {
                "type": "bubble",
                "body": {
                    "type": "box",
                    "layout": "vertical",
                    "contents": [{"type": "text", "text": f"{artist} report"}],
                },
            },
        }


class FakeLlm:
    """Stands in for GeminiTextClient: returns canned text or raises the given error."""

    enabled = True

    def __init__(self, text: str = "", error: Exception | None = None) -> None:
        self.text = text
        self.error = error
        self.prompts: list[str] = []

    def generate(self, prompt: str, **kwargs) -> str:
        self.prompts.append(prompt)
        if self.error is not None:
            raise self.error
        return self.text


class RecordingMessagingApi:
    """Captures LINE replies as plain dicts."""

    def __init__(self) -> None:
        self.replies: list[list[dict]] = []

    def reply_message(self, request) -> None:
        self.replies.append([message.to_dict() for message in request.messages])


def make_settings(**overrides) -> Settings:
    return Settings(**{"base_dir": REPO_ROOT, **overrides})


def make_deps(
    *,
    base_dir: Path = REPO_ROOT,
    agent=None,
    radar_repo=None,
    llm=None,
    rng: random.Random | None = None,
    clock: Callable[[], float] = time,
    **settings_overrides,
) -> BotDeps:
    settings = make_settings(base_dir=base_dir, **settings_overrides)
    return BotDeps(
        settings=settings,
        agent=agent or KpopAnalysisAgent(config=settings),
        radar_repo=radar_repo or KpopRadarRepository(settings),
        llm=llm or GeminiTextClient(None, settings.gemini_model),
        rng=rng or random.Random(),
        clock=clock,
    )


def make_app(
    deps: BotDeps | None = None,
    *,
    line_dedupe_path: Path | None = None,
    line_api: RecordingMessagingApi | None = None,
) -> Flask:
    """Build an app; passing line_dedupe_path turns on the LINE adapter with fake credentials."""
    deps = deps or make_deps()
    if line_dedupe_path is None:
        return create_app(deps)
    deps = dataclasses.replace(
        deps,
        settings=dataclasses.replace(
            deps.settings,
            line_channel_secret="test-secret",
            line_channel_access_token="test-token",
        ),
    )
    api = line_api or RecordingMessagingApi()

    @contextmanager
    def messaging_api_factory():
        yield api

    # Each message lands well outside the debounce window unless a test says otherwise.
    ticks = itertools.count(start=1_000, step=60)
    return create_app(
        deps,
        messaging_api_factory=messaging_api_factory,
        line_events=LineEventGuard(line_dedupe_path, monotonic=lambda: next(ticks)),
    )
