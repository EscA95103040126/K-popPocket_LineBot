from __future__ import annotations

import os

# Runs before any test module imports src.config, so settings are built without the
# developer's .env and without credentials exported in the shell.
os.environ["KPOP_AGENT_ENV_FILE"] = ""
for _name in (
    "LINE_CHANNEL_ACCESS_TOKEN",
    "LINE_CHANNEL_SECRET",
    "NAVER_CLIENT_ID",
    "NAVER_CLIENT_SECRET",
    "GEMINI_API_KEY",
    "GEMINI_MODEL",
    "YOUTUBE_API_KEY",
    "SUPABASE_URL",
    "SUPABASE_SERVICE_ROLE_KEY",
    "DATABASE_PATH",
    "MOCK_DATA_DIR",
    "PORT",
):
    os.environ.pop(_name, None)
