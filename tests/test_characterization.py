"""Golden-master tests that pin the bot's observable behaviour on every channel.

The same conversation corpus is replayed through the three entry points the bot
exposes (JSON ``/analyze``, the mock ``/webhook`` and the real LINE reply path) and
the outputs are compared against snapshots in ``tests/golden/``. External services,
randomness and per-process state are all pinned so the snapshots are reproducible.

Regenerate snapshots after an intentional behaviour change with:

    UPDATE_GOLDEN=1 pytest tests/test_characterization.py
"""

from __future__ import annotations

import json
import os
import random
from collections import OrderedDict
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests

from src.web.app_factory import line_adapter_of
from tests.fakes import (
    REPO_ROOT,
    SAVED_ITEM_ID,
    FakeAgent,
    FakeRadarRepository,
    RecordingMessagingApi,
    make_app,
    make_deps,
)


GOLDEN_DIR = Path(__file__).parent / "golden"
UPDATE_GOLDEN = os.getenv("UPDATE_GOLDEN") == "1"
SEED = 20261023


def _bias_radar_full_run() -> list[str]:
    questions = json.loads(
        (REPO_ROOT / "data/play_zone/bias_radar_questions.json").read_text(encoding="utf-8")
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


def _block_network(*args, **kwargs):
    raise requests.ConnectionError("network disabled in characterization tests")


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    monkeypatch.setattr(requests, "get", _block_network)
    monkeypatch.setattr(requests, "post", _block_network)


def _fresh_deps():
    # A new app per conversation gives every conversation fresh state.
    return make_deps(agent=FakeAgent(), radar_repo=FakeRadarRepository(), rng=random.Random(SEED))


def _run_analyze(messages: list[str], user_id: str, tmp_path: Path) -> list:
    client = make_app(_fresh_deps()).test_client()
    outputs = []
    for message in messages:
        response = client.post("/analyze", json={"message": message, "user_id": user_id})
        outputs.append({"status": response.status_code, "body": response.get_json()})
    return outputs


def _run_mock_webhook(messages: list[str], user_id: str, tmp_path: Path) -> list:
    client = make_app(_fresh_deps()).test_client()
    outputs = []
    for message in messages:
        response = client.post("/webhook", json={"message": message, "user_id": user_id})
        body = response.get_data(as_text=True)
        outputs.append({
            "status": response.status_code,
            # The webhook returns JSON text with an HTML content type; compare it parsed.
            "body": json.loads(body) if body.startswith("{") else body,
        })
    return outputs


def _run_line(messages: list[str], user_id: str, tmp_path: Path) -> list:
    api = RecordingMessagingApi()
    app = make_app(_fresh_deps(), line_dedupe_path=tmp_path / f"{user_id}.json", line_api=api)
    adapter = line_adapter_of(app)
    outputs = []
    for index, message in enumerate(messages):
        api.replies = []
        event = SimpleNamespace(
            webhook_event_id=f"{user_id}-{index}",
            reply_token=f"token-{index}",
            source=SimpleNamespace(user_id=user_id),
        )
        with app.test_request_context("/webhook", method="POST"):
            adapter.reply_to_event(event, message)
        outputs.append(api.replies)
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


RUNNERS = {"analyze": _run_analyze, "mock_webhook": _run_mock_webhook, "line": _run_line}


@pytest.mark.parametrize("channel", list(RUNNERS))
def test_channel_matches_golden(channel, tmp_path) -> None:
    results: dict[str, list] = OrderedDict()
    for name, messages in CONVERSATIONS.items():
        results[name] = RUNNERS[channel](messages, f"user-{name}", tmp_path)
    _assert_matches_golden(channel, results)
