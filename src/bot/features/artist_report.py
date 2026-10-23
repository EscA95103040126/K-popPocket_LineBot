from __future__ import annotations

import re
import unicodedata
from typing import TYPE_CHECKING

from src.agent import SUPPORTED_ARTISTS
from src.bot.dispatcher import MessageContext
from src.bot.reply import Reply
from src.router import ARTIST_PATTERNS, route_message

if TYPE_CHECKING:
    from src.agent import KpopAnalysisAgent


def is_full_artist_report_request(message: str) -> bool:
    normalized = message.strip().casefold()
    if normalized in {artist.casefold() for artist in SUPPORTED_ARTISTS}:
        return True
    if not _mentions_supported_artist(message):
        return False
    return bool(
        re.search(r"(^|\s)(分析|analyze|report|보고서|분석)\s*", normalized)
        and route_message(message).artist in SUPPORTED_ARTISTS
    )


def _mentions_supported_artist(message: str) -> bool:
    normalized = unicodedata.normalize("NFKC", message)
    return any(
        artist in SUPPORTED_ARTISTS and pattern.search(normalized)
        for artist, pattern in ARTIST_PATTERNS.items()
    )


def report_artist(context: MessageContext) -> str:
    artist = route_message(context.text).artist
    if artist and is_full_artist_report_request(context.text):
        return artist
    if context.artist_hint:
        return route_message(f"分析 {context.artist_hint}").artist
    return ""


class ArtistReportFeature:
    """Full artist market report backed by the offline ABSA cache."""

    def __init__(self, agent: KpopAnalysisAgent) -> None:
        self.agent = agent

    def artist_report_reply(self, context: MessageContext) -> Reply:
        artist = report_artist(context)
        artist_cache = self.agent.get_artist_analysis_cache(
            artist,
            period_months=route_message(context.text).period_months,
        )
        return Reply(
            report=artist_cache["report"],
            flex=artist_cache["flex"],
            alt_text=f"{artist_cache['artist']} K-pop 分析報告",
            cache={
                "type": artist_cache.get("cache_type", "artist"),
                "artist": artist_cache["artist"],
                "cached_at": artist_cache["cached_at"],
            },
        )
