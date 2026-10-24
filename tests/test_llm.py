from types import SimpleNamespace

import pytest

from src.bot import llm as llm_module
from src.bot.llm import GeminiTextClient


def test_generate_switches_off_thinking(monkeypatch) -> None:
    # A thinking model spent 344 of 360 output tokens on thoughts and answered in 19 chars.
    sent = {}

    def fake_post(url, params, json, timeout):
        sent.update(json)
        return SimpleNamespace(
            status_code=200,
            raise_for_status=lambda: None,
            json=lambda: {"candidates": [{"content": {"parts": [{"text": "好"}]}}]},
        )

    monkeypatch.setattr(llm_module.requests, "post", fake_post)

    GeminiTextClient("key", "gemini-3.5-flash").generate(
        "prompt", temperature=0.4, max_output_tokens=360
    )

    assert sent["generationConfig"]["thinkingConfig"] == {"thinkingBudget": 0}
    assert sent["generationConfig"]["maxOutputTokens"] == 360


def _response(status: int, text: str = "好"):
    def raise_for_status():
        if status >= 400:
            raise llm_module.requests.HTTPError(
                f"{status}", response=SimpleNamespace(status_code=status)
            )

    return SimpleNamespace(
        status_code=status,
        raise_for_status=raise_for_status,
        json=lambda: {"candidates": [{"content": {"parts": [{"text": text}]}}]},
    )


def test_generate_retries_once_after_a_quick_503(monkeypatch) -> None:
    replies = [_response(503), _response(200, "第二次成功")]
    monkeypatch.setattr(llm_module.requests, "post", lambda *a, **k: replies.pop(0))
    monkeypatch.setattr(llm_module.time, "sleep", lambda seconds: None)

    text = GeminiTextClient("key", "m").generate("p", temperature=0.4, max_output_tokens=10)

    assert text == "第二次成功"
    assert replies == []


def test_generate_does_not_retry_quota_errors(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(
        llm_module.requests, "post", lambda *a, **k: calls.append(1) or _response(429)
    )

    with pytest.raises(llm_module.requests.HTTPError):
        GeminiTextClient("key", "m").generate("p", temperature=0.4, max_output_tokens=10)

    assert calls == [1]
