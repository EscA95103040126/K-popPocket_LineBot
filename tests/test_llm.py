from types import SimpleNamespace

from src.bot import llm as llm_module
from src.bot.llm import GeminiTextClient


def test_generate_switches_off_thinking(monkeypatch) -> None:
    # A thinking model spent 344 of 360 output tokens on thoughts and answered in 19 chars.
    sent = {}

    def fake_post(url, params, json, timeout):
        sent.update(json)
        return SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: {"candidates": [{"content": {"parts": [{"text": "好"}]}}]},
        )

    monkeypatch.setattr(llm_module.requests, "post", fake_post)

    GeminiTextClient("key", "gemini-3.5-flash").generate(
        "prompt", temperature=0.4, max_output_tokens=360
    )

    assert sent["generationConfig"]["thinkingConfig"] == {"thinkingBudget": 0}
    assert sent["generationConfig"]["maxOutputTokens"] == 360
