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

    @classmethod
    def from_settings(cls, settings: Settings) -> BotDeps:
        return cls(
            settings=settings,
            agent=KpopAnalysisAgent(config=settings),
            radar_repo=KpopRadarRepository(settings),
            llm=GeminiTextClient(settings.gemini_api_key, settings.gemini_model),
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


def build_bot(deps: BotDeps) -> Bot:
    catalog = PlayZoneCatalog(deps.settings.base_dir)
    pocket = PocketFeature(deps.radar_repo)
    features = Features(
        catalog=catalog,
        pocket=pocket,
        ai_curator=AiCuratorFeature(
            catalog, deps.llm, deps.rng, deps.clock, is_fixed_command=is_fixed_command
        ),
        bias_radar=BiasRadarFeature(catalog, deps.rng, deps.clock),
        member_quiz=MemberQuizFeature(catalog, deps.rng),
        daily_kpop=DailyKpopFeature(catalog, deps.radar_repo, pocket, deps.rng),
        photo_card=PhotoCardFeature(catalog, pocket, deps.rng),
        charts=ChartFeature(deps.agent),
        artist_report=ArtistReportFeature(deps.agent),
    )
    return Bot(deps=deps, features=features, dispatcher=build_dispatcher(features))
