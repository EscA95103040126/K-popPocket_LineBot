from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import dataclass, field
from time import time

from src.agent import KpopAnalysisAgent
from src.bot.catalog import PlayZoneCatalog
from src.bot.dispatcher import Dispatcher
from src.bot.features.ai_curator import AiCuratorFeature
from src.bot.features.artist_report import ArtistReportFeature
from src.bot.features.bias_radar import BiasRadarFeature
from src.bot.features.charts import ChartFeature
from src.bot.features.daily_kpop import DailyKpopFeature
from src.bot.features.member_quiz import MemberQuizFeature
from src.bot.features.photo_card import PhotoCardFeature
from src.bot.features.pocket import PocketFeature
from src.bot.llm import GeminiTextClient
from src.bot.routing import build_dispatcher, is_fixed_command
from src.bot.semantic_index import SemanticMemberRanker
from src.bot.sessions import InMemorySessionStore, SessionStore, build_session_store
from src.config import Settings
from src.tools.kpop_radar import KpopRadarRepository


@dataclass
class BotDeps:
    """Everything the bot reaches outside its own code; tests swap these for fakes."""

    settings: Settings
    agent: KpopAnalysisAgent
    radar_repo: KpopRadarRepository
    llm: GeminiTextClient
    rng: random.Random = field(default_factory=random.Random)
    clock: Callable[[], float] = time
    # None means per-process memory (see build_bot).
    sessions: SessionStore | None = None
    # AI 入坑 v2 semantic ranking; it still falls back to v1 when models/ is missing.
    semantic_curator: bool = False

    @classmethod
    def from_settings(cls, settings: Settings) -> BotDeps:
        radar_repo = KpopRadarRepository(settings)
        return cls(
            settings=settings,
            agent=KpopAnalysisAgent(config=settings),
            radar_repo=radar_repo,
            llm=GeminiTextClient(settings.gemini_api_key, settings.gemini_model),
            sessions=build_session_store(radar_repo.client),
            semantic_curator=True,
        )


@dataclass
class Features:
    catalog: PlayZoneCatalog
    pocket: PocketFeature
    ai_curator: AiCuratorFeature
    bias_radar: BiasRadarFeature
    member_quiz: MemberQuizFeature
    daily_kpop: DailyKpopFeature
    photo_card: PhotoCardFeature
    charts: ChartFeature
    artist_report: ArtistReportFeature


@dataclass
class Bot:
    deps: BotDeps
    features: Features
    dispatcher: Dispatcher
    sessions: SessionStore


def build_bot(deps: BotDeps) -> Bot:
    catalog = PlayZoneCatalog(deps.settings.base_dir)
    pocket = PocketFeature(deps.radar_repo)
    sessions = deps.sessions or InMemorySessionStore(clock=deps.clock)
    features = Features(
        catalog=catalog,
        pocket=pocket,
        ai_curator=AiCuratorFeature(
            catalog,
            deps.llm,
            deps.rng,
            sessions,
            is_fixed_command=is_fixed_command,
            semantic_ranker_loader=(
                (
                    lambda: SemanticMemberRanker.load(
                        deps.settings.base_dir, catalog.load_bias_radar_members()
                    )
                )
                if deps.semantic_curator
                else None
            ),
        ),
        bias_radar=BiasRadarFeature(catalog, deps.rng, sessions),
        member_quiz=MemberQuizFeature(catalog, deps.rng),
        daily_kpop=DailyKpopFeature(catalog, deps.radar_repo, pocket, deps.rng),
        photo_card=PhotoCardFeature(catalog, pocket, deps.rng),
        charts=ChartFeature(deps.agent),
        artist_report=ArtistReportFeature(deps.agent),
    )
    return Bot(
        deps=deps,
        features=features,
        dispatcher=build_dispatcher(features),
        sessions=sessions,
    )
