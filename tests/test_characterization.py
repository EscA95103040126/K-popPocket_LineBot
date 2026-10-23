"""Golden-master tests that pin the bot's observable behaviour on every channel.

The same conversation corpus is replayed through the three entry points the bot
exposes (JSON ``/analyze``, the mock ``/webhook`` and the real LINE reply path) and
the outputs are compared against snapshots in ``tests/golden/``. External services,
randomness and per-process state are all pinned so the snapshots are reproducible.

Regenerate snapshots after an intentional behaviour change with:

    UPDATE_GOLDEN=1 pytest tests/test_characterization.py
"""

from __future__ import annotations

import itertools
import json
import os
import random
from collections import OrderedDict
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests

import app as app_module
from app import app


GOLDEN_DIR = Path(__file__).parent / "golden"
UPDATE_GOLDEN = os.getenv("UPDATE_GOLDEN") == "1"
SEED = 20261023
SAVED_ITEM_ID = "00000000-0000-0000-0000-000000000001"


def _bias_radar_full_run() -> list[str]:
    questions = json.loads(
        (app_module.settings.base_dir / "data/play_zone/bias_radar_questions.json").read_text(
            encoding="utf-8"
        )
    )
    return ["本命雷達測驗"] + [
        f"本命雷達:{index}:{question['options'][1]}"
        for index, question in enumerate(questions)
    ]


CONVERSATIONS: dict[str, list[str]] = {
    "artist_picker": ["分析", "選擇藝人"],
    "help": ["help"],
    "pocket": [
        "我的口袋",
        "action=view_saved&type=mv",
        "action=open_pref",
        "action=set_pref&gender=girl_group",
        f"action=save_item&item_id={SAVED_ITEM_ID}",
        f"action=save_item&item_id={SAVED_ITEM_ID}",
        "action=view_saved&type=mv",
        "action=save_item",
    ],
    "play_zone": ["互動專區", "測驗"],
    "ai_curator_entry": ["AI入坑", "策展人"],
    "ai_curator_preference": [
        "我想入坑清冷感、舞台強的女團",
        "為什麼推薦她",
    ],
    "ai_curator_persona": ["我喜歡姐系的", "推薦 vocal 強的男團"],
    "ai_curator_reason_without_context": ["為什麼推薦 Karina"],
    "bias_radar_full": _bias_radar_full_run(),
    "bias_radar_interrupted": ["本命雷達", "每日 MV", "女團", "我的口袋", "help"],
    "fan_attribute_quiz": [
        "粉絲屬性測驗",
        "粉絲屬性測驗:1:1,0,0",
        "粉絲屬性測驗:result:3,1,1",
    ],
    "member_quiz": ["認人測驗", "認人答案:jiwoo_001:A", "認人答案:jiwoo_001:B", "再一題"],
    "daily_kpop": ["每日一首", "每日 MV", "每日直拍", "每日經典舞台", "每日 經典舞台"],
    "photo_card": ["神圖抽卡", "抽卡", "再抽一張"],
    "weekly_chart": ["本週榜單", "歷史週榜:2026-05-11", "歷史週榜:20260504"],
    "artist_report": ["分析 aespa", "IVE", "分析 NCT 一個月", "분석 ILLIT"],
    "fallback": ["你好", "aespa 最近怎樣", "kpop 粉絲留言"],
}


class FakeSaveResult:
    def __init__(self, status: str) -> None:
        self.status = status

    @property
    def saved(self) -> bool:
        return self.status == "saved"

    @property
    def duplicate(self) -> bool:
        return self.status == "duplicate"


class FakeRadarRepository:
    enabled = True

    def __init__(self) -> None:
        self.preference = "all"
        self.saved_item_ids: list[str] = []
        self.item = {
            "id": SAVED_ITEM_ID,
            "item_type": "mv",
            "gender_category": "girl_group",
            "artist": "NMIXX",
            "member": "",
            "title": "DASH",
            "url": "https://example.com/nmixx-dash",
        }

    def status(self) -> dict:
        return {"ok": True}

    def ensure_user(self, line_user_id: str) -> None:
        pass

    def get_preference(self, line_user_id: str) -> str:
        return self.preference

    def upsert_preference(self, line_user_id: str, preferred_gender: str) -> str:
        self.preference = preferred_gender
        return preferred_gender

    def saved_counts(self, line_user_id: str) -> dict[str, int]:
        return {"mv": len(self.saved_item_ids), "fancam": 0, "photo": 0}

    def list_saved_items(self, line_user_id: str, item_type: str) -> list[dict[str, str]]:
        if item_type == "mv" and self.saved_item_ids:
            return [self.item]
        return []

    def save_item(self, line_user_id: str, item_id: str) -> FakeSaveResult:
        if item_id in self.saved_item_ids:
            return FakeSaveResult("duplicate")
        self.saved_item_ids.append(item_id)
        return FakeSaveResult("saved")

    def recommend_daily_mv(self, line_user_id: str) -> dict[str, str]:
        return self.item

    def find_item_by_url(self, item_type: str, url: str) -> dict[str, str] | None:
        if item_type == "mv" and url == self.item["url"]:
            return self.item
        return None


class FakeAgent:
    def get_weekly_chart_cache(self) -> dict:
        return {
            "report": "# 本週 K-pop 榜單\n1. Fake Song - Fake Artist",
            "cached_at": "2026-10-20T00:00:00+00:00",
            "chart": {"chart_date": "2026-10-12"},
        }

    def generate_weekly_chart_report_for_date(self, chart_date: str) -> str:
        return f"# Bugs 歷史週榜\n榜單日期：{chart_date}\n1. Old Song - Old Artist"

    def list_weekly_chart_dates(self, limit: int = 12, min_items: int = 1) -> list[str]:
        return ["2026-10-12", "2026-10-05", "2026-09-28"][:limit]

    def get_artist_analysis_cache(self, artist: str, period_months: int = 3) -> dict:
        return {
            "report": f"# {artist} 近期市場與輿論分析\n期間：{period_months} 個月",
            "artist": artist,
            "cached_at": "2026-10-11T00:00:00+00:00",
            "cache_type": "absa",
            "flex": {"type": "bubble", "body": {"type": "box", "layout": "vertical",
                     "contents": [{"type": "text", "text": f"{artist} report"}]}},
        }

    def analyze_message_local(self, message: str) -> str:
        return f"# local analysis\n{message}"

    def build_flex_message(self, report: str) -> dict:
        return {"type": "bubble", "body": {"type": "box", "layout": "vertical",
                "contents": [{"type": "text", "text": report[:40]}]}}


class FakeApiClient:
    def __init__(self, configuration) -> None:
        pass

    def __enter__(self) -> "FakeApiClient":
        return self

    def __exit__(self, *exc) -> None:
        return None


class RecordingMessagingApi:
    replies: list[list[dict]] = []

    def __init__(self, api_client) -> None:
        pass

    def reply_message(self, request) -> None:
        RecordingMessagingApi.replies.append(
            [message.to_dict() for message in request.messages]
        )


def _block_network(*args, **kwargs):
    raise requests.ConnectionError("network disabled in characterization tests")


@pytest.fixture
def bot_env(monkeypatch, tmp_path):
    monkeypatch.setattr(requests, "get", _block_network)
    monkeypatch.setattr(requests, "post", _block_network)
    monkeypatch.setattr(app_module, "agent", FakeAgent())
    monkeypatch.setattr(app_module, "LINE_EVENT_DEDUPE_PATH", tmp_path / "seen.json")
    monkeypatch.setattr(app_module, "line_processed_event_ids", None)
    monkeypatch.setattr(app_module, "line_configuration", object())
    monkeypatch.setattr(app_module, "ApiClient", FakeApiClient)
    monkeypatch.setattr(app_module, "MessagingApi", RecordingMessagingApi)
    # Each message arrives well outside the debounce window; debounce has its own tests.
    clock = itertools.count(start=1_000, step=60)
    monkeypatch.setattr(app_module, "monotonic", lambda: next(clock))

    def reset() -> None:
        monkeypatch.setattr(app_module, "radar_repo", FakeRadarRepository())
        monkeypatch.setattr(app_module, "photo_card_queue", [])
        monkeypatch.setattr(app_module, "photo_card_source_key", ())
        monkeypatch.setattr(app_module, "member_quiz_queue", [])
        monkeypatch.setattr(app_module, "member_quiz_source_key", ())
        app_module.daily_kpop_queues.clear()
        app_module.daily_kpop_source_keys.clear()
        app_module.bias_radar_sessions.clear()
        app_module.ai_curator_reason_contexts.clear()
        app_module.line_recent_message_keys.clear()
        app_module.line_processing_event_ids.clear()
        random.seed(SEED)

    return reset


def _run_analyze(messages: list[str], user_id: str) -> list:
    client = app.test_client()
    outputs = []
    for message in messages:
        response = client.post("/analyze", json={"message": message, "user_id": user_id})
        outputs.append({"status": response.status_code, "body": response.get_json()})
    return outputs


def _run_mock_webhook(messages: list[str], user_id: str, monkeypatch) -> list:
    monkeypatch.setattr(app_module, "line_handler", None)
    client = app.test_client()
    outputs = []
    for message in messages:
        response = client.post("/webhook", json={"message": message, "user_id": user_id})
        outputs.append({"status": response.status_code, "body": response.get_data(as_text=True)})
    return outputs


def _run_line(messages: list[str], user_id: str) -> list:
    outputs = []
    for index, message in enumerate(messages):
        RecordingMessagingApi.replies = []
        event = SimpleNamespace(
            webhook_event_id=f"{user_id}-{index}",
            reply_token=f"token-{index}",
            source=SimpleNamespace(user_id=user_id),
        )
        with app.test_request_context("/webhook", method="POST"):
            app_module._reply_line_event(event, message)
        outputs.append(RecordingMessagingApi.replies)
    return outputs


def _assert_matches_golden(channel: str, actual: dict) -> None:
    path = GOLDEN_DIR / f"{channel}.json"
    serialized = json.dumps(actual, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if UPDATE_GOLDEN or not path.exists():
        GOLDEN_DIR.mkdir(exist_ok=True)
        path.write_text(serialized, encoding="utf-8")
        return
    expected = json.loads(path.read_text(encoding="utf-8"))
    actual_roundtrip = json.loads(serialized)
    for name in expected:
        assert actual_roundtrip.get(name) == expected[name], f"{channel}/{name} drifted"
    assert set(actual_roundtrip) == set(expected)


@pytest.mark.parametrize("channel", ["analyze", "mock_webhook", "line"])
def test_channel_matches_golden(channel, bot_env, monkeypatch) -> None:
    results: dict[str, list] = OrderedDict()
    for name, messages in CONVERSATIONS.items():
        bot_env()
        user_id = f"user-{name}"
        if channel == "analyze":
            results[name] = _run_analyze(messages, user_id)
        elif channel == "mock_webhook":
            results[name] = _run_mock_webhook(messages, user_id, monkeypatch)
        else:
            results[name] = _run_line(messages, user_id)
    _assert_matches_golden(channel, results)
