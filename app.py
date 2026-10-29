"""WSGI entry point (``gunicorn app:app``); the app itself is built in src/web/app_factory.py."""

from __future__ import annotations

from src.bot.preference_probe import start_preference_probe
from src.config import settings
from src.web.app_factory import create_app

app = create_app()
# 只有設定 PREFERENCE_PROBE_RUNS 時才在背景量偏好解析的延遲。
start_preference_probe(settings.gemini_api_key, settings.base_dir)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=settings.port)
