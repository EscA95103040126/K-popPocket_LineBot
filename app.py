"""WSGI entry point (``gunicorn app:app``); the app itself is built in src/web/app_factory.py."""

from __future__ import annotations

from src.config import settings
from src.web.app_factory import create_app

app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=settings.port)
