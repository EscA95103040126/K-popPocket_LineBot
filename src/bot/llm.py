from __future__ import annotations

import time
from typing import Any

import requests

from src.agent import GEMINI_API_URL, GEMINI_NO_THINKING, GEMINI_REQUEST_TIMEOUT_SECONDS

# The free-tier flash-lite preview answered AI 入坑 prompts in 2-18s, so the bot waits
# longer than the 10s default; it must stay well under gunicorn's 30s worker timeout.
BOT_GEMINI_TIMEOUT_SECONDS = 20
# Gemini sheds load with fast 5xx replies (the Space logged HTTP 503) that usually clear
# within a second. Retry once, and only after a quick failure, so the total wait still
# fits the timeout; 429 means quota is gone and a retry would not help.
GEMINI_RETRYABLE_STATUS_CODES = {500, 502, 503, 504}
GEMINI_RETRY_DELAY_SECONDS = 1.0
GEMINI_RETRY_IF_FAILED_WITHIN_SECONDS = 3.0


class GeminiTextClient:
    """Minimal Gemini generateContent client; disabled when no API key is configured."""

    def __init__(
        self,
        api_key: str | None,
        model: str,
        timeout_seconds: float = GEMINI_REQUEST_TIMEOUT_SECONDS,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    def generate(
        self,
        prompt: str,
        *,
        temperature: float,
        max_output_tokens: int,
        response_mime_type: str | None = None,
    ) -> str:
        generation_config: dict[str, Any] = {
            "temperature": temperature,
            "maxOutputTokens": max_output_tokens,
            "thinkingConfig": GEMINI_NO_THINKING,
        }
        if response_mime_type:
            generation_config["responseMimeType"] = response_mime_type
        payload = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": generation_config,
        }
        started = time.monotonic()
        response = self._post(payload)
        if (
            response.status_code in GEMINI_RETRYABLE_STATUS_CODES
            and time.monotonic() - started < GEMINI_RETRY_IF_FAILED_WITHIN_SECONDS
        ):
            time.sleep(GEMINI_RETRY_DELAY_SECONDS)
            response = self._post(payload)
        response.raise_for_status()
        data = response.json()
        return data["candidates"][0]["content"]["parts"][0].get("text", "")

    def _post(self, payload: dict[str, Any]) -> requests.Response:
        return requests.post(
            GEMINI_API_URL.format(model=self.model),
            params={"key": self.api_key},
            json=payload,
            timeout=self.timeout_seconds,
        )
