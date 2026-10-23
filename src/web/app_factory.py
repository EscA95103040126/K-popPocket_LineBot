from __future__ import annotations

import sqlite3

from flask import Flask, abort, jsonify, request, send_from_directory

from src.bot.container import Bot, BotDeps, build_bot
from src.bot.dispatcher import MessageContext
from src.bot.features.bias_radar import safe_bias_radar_image_filename
from src.bot.features.member_quiz import safe_member_quiz_image_filename
from src.bot.line_events import LineEventGuard
from src.config import Settings, settings as default_settings
from src.tools.bugs_chart import fetch_bugs_weekly_chart
from src.tools.naver_news import NaverNewsClient

try:
    from linebot.v3.exceptions import InvalidSignatureError

    from src.bot.line_adapter import LineAdapter, MessagingApiFactory
except ImportError:  # pragma: no cover - lets local mock mode run without LINE SDK.
    InvalidSignatureError = Exception
    LineAdapter = None
    MessagingApiFactory = None

BOT_EXTENSION = "kpop_bot"
LINE_EXTENSION = "kpop_line"


def create_app(
    deps: BotDeps | None = None,
    *,
    messaging_api_factory: MessagingApiFactory | None = None,
    line_events: LineEventGuard | None = None,
) -> Flask:
    """Build the Flask app around a bot assembled from ``deps`` (defaults: real services)."""
    deps = deps or BotDeps.from_settings(default_settings)
    bot = build_bot(deps)
    line = _build_line_adapter(bot, messaging_api_factory, line_events)

    app = Flask(__name__)
    app.extensions[BOT_EXTENSION] = bot
    app.extensions[LINE_EXTENSION] = line
    settings = deps.settings
    features = bot.features

    @app.get("/")
    def index() -> tuple[dict, int]:
        return {
            "status": "ok",
            "service": "kpop-agent",
            "health": "/health",
            "webhook": "/webhook",
        }, 200

    @app.post("/")
    def root_webhook() -> tuple[str, int]:
        return webhook()

    @app.get("/health")
    def health() -> tuple[dict, int]:
        sqlite_status = _sqlite_status(settings)
        bugs_tool_available = callable(fetch_bugs_weekly_chart)
        radar_repo = deps.radar_repo
        status = "ok" if sqlite_status["ok"] and bugs_tool_available else "degraded"
        return {
            "status": status,
            "sqlite_ok": sqlite_status["ok"],
            "sqlite": sqlite_status,
            "bugs_tool_available": bugs_tool_available,
            "naver_mode": _naver_mode(settings),
            "gemini_mode": _mode(not deps.llm.enabled),
            "line_mode": _mode(line is None),
            "supabase_mode": "real" if radar_repo.enabled else "disabled",
            "supabase": radar_repo.status(),
        }, 200 if status == "ok" else 503

    @app.get("/play-zone/images/<path:filename>")
    def play_zone_member_quiz_image(filename: str):
        safe_filename = safe_member_quiz_image_filename(filename)
        if safe_filename is None:
            abort(404)
        return send_from_directory(features.member_quiz.member_quiz_image_dir(), safe_filename)

    @app.get("/play-zone/images/flex/<path:filename>")
    def play_zone_member_quiz_flex_image(filename: str):
        safe_filename = safe_member_quiz_image_filename(filename)
        if safe_filename is None:
            abort(404)
        return features.member_quiz.send_member_quiz_flex_image(safe_filename)

    @app.get("/play-zone/radar-image/<path:filename>")
    def play_zone_bias_radar_image(filename: str):
        safe_filename = safe_bias_radar_image_filename(filename)
        if safe_filename is None:
            abort(404)
        return send_from_directory(features.bias_radar.bias_radar_image_dir(), safe_filename)

    @app.post("/analyze")
    def analyze() -> tuple[dict, int]:
        payload = request.get_json(silent=True) or {}
        message = str(payload.get("message") or "").strip()
        artist = str(payload.get("artist") or "").strip()
        user_id = str(payload.get("user_id") or "analyze-user")
        if not message and artist:
            message = f"分析 {artist}"
        if not message:
            return {"error": "message or artist is required"}, 400
        context = MessageContext(text=message, user_id=user_id, artist_hint=artist)
        return bot.dispatcher.dispatch(context).to_json(), 200

    @app.post("/webhook")
    def webhook() -> tuple[str, int]:
        if line is None:
            payload = request.get_json(silent=True) or {}
            message = _extract_mock_message(payload)
            if message:
                user_id = str(payload.get("user_id") or "mock-user")
                reply = bot.dispatcher.dispatch(MessageContext(text=message, user_id=user_id)).text
                return jsonify({"mock_reply": reply}).get_data(as_text=True), 200
            return "OK", 200

        try:
            line.handle(
                request.get_data(as_text=True),
                request.headers.get("X-Line-Signature", ""),
            )
        except InvalidSignatureError:
            abort(400)
        return "OK", 200

    return app


def bot_of(app: Flask) -> Bot:
    return app.extensions[BOT_EXTENSION]


def line_adapter_of(app: Flask) -> LineAdapter | None:
    return app.extensions[LINE_EXTENSION]


def _build_line_adapter(
    bot: Bot,
    messaging_api_factory: MessagingApiFactory | None,
    line_events: LineEventGuard | None,
) -> LineAdapter | None:
    settings = bot.deps.settings
    if LineAdapter is None or settings.use_line_mock:
        return None
    return LineAdapter(
        bot=bot,
        channel_secret=settings.line_channel_secret,
        access_token=settings.line_channel_access_token,
        events=line_events
        or LineEventGuard(
            settings.base_dir / "data" / "cache" / "line_seen_events.json",
            clock=bot.deps.clock,
        ),
        messaging_api_factory=messaging_api_factory,
    )


def _extract_mock_message(payload: dict) -> str:
    if "message" in payload:
        return str(payload["message"])
    events = payload.get("events") or []
    if not events:
        return ""
    message = events[0].get("message") or {}
    return str(message.get("text") or "")


def _mode(is_mock: bool) -> str:
    return "mock" if is_mock else "real"


def _naver_mode(settings: Settings) -> str:
    if settings.use_naver_mock:
        return "mock"
    return "real" if NaverNewsClient(settings).real_api_available() else "mock"


def _sqlite_status(settings: Settings) -> dict:
    if not settings.database_path.exists():
        return {
            "ok": False,
            "path": str(settings.database_path),
            "error": "database file not found",
        }

    try:
        with sqlite3.connect(settings.database_path) as conn:
            table_exists = conn.execute(
                """
                SELECT 1
                FROM sqlite_master
                WHERE type = 'table' AND name = 'chart_history'
                """
            ).fetchone()
            if not table_exists:
                return {
                    "ok": False,
                    "path": str(settings.database_path),
                    "error": "chart_history table not found",
                }

            total_rows, min_date, max_date = conn.execute(
                "SELECT COUNT(*), MIN(chart_date), MAX(chart_date) FROM chart_history"
            ).fetchone()
            return {
                "ok": True,
                "path": str(settings.database_path),
                "chart_history_rows": total_rows,
                "chart_date_min": min_date,
                "chart_date_max": max_date,
            }
    except sqlite3.Error as exc:
        return {
            "ok": False,
            "path": str(settings.database_path),
            "error": str(exc),
        }
