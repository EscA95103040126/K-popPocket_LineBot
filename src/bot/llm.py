from __future__ import annotations

from typing import Any

import requests

from src.agent import GEMINI_API_URL, GEMINI_REQUEST_TIMEOUT_SECONDS


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
        }
        if response_mime_type:
            generation_config["responseMimeType"] = response_mime_type
        response = requests.post(
            GEMINI_API_URL.format(model=self.model),
            params={"key": self.api_key},
            json={
                "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                "generationConfig": generation_config,
            },
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        data = response.json()
        return data["candidates"][0]["content"]["parts"][0].get("text", "")
