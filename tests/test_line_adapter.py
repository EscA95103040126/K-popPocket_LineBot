from __future__ import annotations

import base64
import hashlib
import hmac
import json

from tests.fakes import RecordingMessagingApi, make_app


def _event(event_type: str, **fields) -> dict:
    return {
        "type": event_type,
        "timestamp": 1_760_000_000_000,
        "source": {"type": "user", "userId": "U-line-test"},
        "replyToken": f"reply-{event_type}",
        "mode": "active",
        "webhookEventId": f"event-{event_type}-{len(fields)}",
        "deliveryContext": {"isRedelivery": False},
        **fields,
    }


def _post_signed(client, events: list[dict]):
    body = json.dumps({"destination": "U-bot", "events": events})
    digest = hmac.new(b"test-secret", body.encode("utf-8"), hashlib.sha256).digest()
    return client.post(
        "/webhook",
        data=body,
        headers={
            "X-Line-Signature": base64.b64encode(digest).decode("ascii"),
            "Content-Type": "application/json",
        },
    )


def test_signed_text_message_is_routed_and_replied(tmp_path) -> None:
    api = RecordingMessagingApi()
    client = make_app(line_dedupe_path=tmp_path / "seen.json", line_api=api).test_client()

    response = _post_signed(
        client,
        [_event("message", message={"type": "text", "id": "1", "text": "help", "quoteToken": "q"})],
    )

    assert response.status_code == 200
    assert len(api.replies) == 1
    assert api.replies[0][0]["text"].startswith("📖 使用說明")


def test_signed_postback_is_routed_and_replied(tmp_path) -> None:
    api = RecordingMessagingApi()
    client = make_app(line_dedupe_path=tmp_path / "seen.json", line_api=api).test_client()

    _post_signed(client, [_event("postback", postback={"data": "互動專區"})])

    assert api.replies[0][0]["altText"] == "K-pop Play Zone"


def test_follow_event_sends_welcome_message(tmp_path) -> None:
    api = RecordingMessagingApi()
    client = make_app(line_dedupe_path=tmp_path / "seen.json", line_api=api).test_client()

    _post_signed(client, [_event("follow", follow={"isUnblocked": False})])

    assert api.replies[0][0]["text"].startswith("🇰🇷 歡迎來到 KPOP 補給站")


def test_unsigned_webhook_is_rejected(tmp_path) -> None:
    api = RecordingMessagingApi()
    client = make_app(line_dedupe_path=tmp_path / "seen.json", line_api=api).test_client()

    response = client.post(
        "/webhook",
        data='{"events": []}',
        headers={"X-Line-Signature": "bad", "Content-Type": "application/json"},
    )

    assert response.status_code == 400
    assert api.replies == []


def test_redelivered_event_is_not_replied_twice(tmp_path) -> None:
    api = RecordingMessagingApi()
    client = make_app(line_dedupe_path=tmp_path / "seen.json", line_api=api).test_client()
    event = _event("message", message={"type": "text", "id": "1", "text": "help", "quoteToken": "q"})

    _post_signed(client, [event])
    _post_signed(client, [event])

    assert len(api.replies) == 1
