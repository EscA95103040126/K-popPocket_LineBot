from __future__ import annotations

import pytest

from src.bot.container import build_bot
from src.bot.dispatcher import Dispatcher, Handler, MessageContext
from src.bot.line_renderer import build_line_messages
from src.bot.reply import QuickReplyAction, Reply
from src.bot.routing import is_fixed_command
from tests.fakes import make_deps


def _context(text: str, user_id: str = "routing-user") -> MessageContext:
    return MessageContext(text=text, user_id=user_id)


def test_dispatcher_returns_first_matching_handler() -> None:
    dispatcher = Dispatcher(
        handlers=[
            Handler("first", lambda c: "a" in c.text, lambda c: Reply(report="first")),
            Handler("second", lambda c: True, lambda c: Reply(report="second")),
        ],
        fallback=Handler("fallback", lambda c: True, lambda c: Reply(report="fallback")),
    )

    assert dispatcher.dispatch(_context("abc")).report == "first"
    assert dispatcher.dispatch(_context("xyz")).report == "second"


def test_dispatcher_uses_fallback_when_nothing_matches() -> None:
    dispatcher = Dispatcher(
        handlers=[Handler("never", lambda c: False, lambda c: Reply(report="never"))],
        fallback=Handler("fallback", lambda c: True, lambda c: Reply(report="fallback")),
    )

    assert dispatcher.resolve(_context("anything")).name == "fallback"


def test_dispatcher_rejects_duplicate_handler_names() -> None:
    handler = Handler("dup", lambda c: True, lambda c: Reply(report=""))

    with pytest.raises(ValueError, match="dup"):
        Dispatcher(handlers=[handler, handler], fallback=handler)


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("分析", "artist_picker"),
        ("我的口袋", "kpop_pocket"),
        ("action=set_pref&gender=all", "kpop_pocket"),
        ("help", "help"),
        ("互動專區", "play_zone"),
        ("AI入坑", "ai_curator_entry"),
        ("我想入坑清冷感、舞台強的女團", "ai_curator_preference"),
        ("本命雷達測驗", "bias_radar_quiz"),
        ("粉絲屬性測驗", "fan_attribute_quiz"),
        ("認人答案:jiwoo_001:A", "member_quiz_answer"),
        ("認人測驗", "member_quiz"),
        ("每日一首", "daily_kpop_menu"),
        ("每日 MV", "daily_kpop_category"),
        ("神圖抽卡", "photo_card"),
        ("歷史週榜:2026-05-11", "historical_weekly_chart"),
        ("本週榜單", "weekly_chart"),
        ("分析 aespa", "artist_report"),
        ("IVE", "artist_report"),
        ("為什麼推薦 Karina", "ai_curator_reason"),
        ("你好", "fixed_command_help"),
    ],
)
def test_routing_table(message: str, expected: str) -> None:
    dispatcher = build_bot(make_deps()).dispatcher

    assert dispatcher.resolve(_context(message)).name == expected


def test_fixed_commands_escape_an_active_bias_radar_session() -> None:
    dispatcher = build_bot(make_deps()).dispatcher
    dispatcher.dispatch(_context("本命雷達測驗"))

    assert dispatcher.resolve(_context("help")).name == "help"
    assert dispatcher.resolve(_context("每日 MV")).name == "bias_radar_quiz"


def test_bias_radar_sessions_are_isolated_per_bot() -> None:
    first = build_bot(make_deps()).dispatcher
    second = build_bot(make_deps()).dispatcher
    first.dispatch(_context("本命雷達測驗"))

    assert first.resolve(_context("女團")).name == "bias_radar_quiz"
    assert second.resolve(_context("女團")).name != "bias_radar_quiz"


@pytest.mark.parametrize(
    ("message", "expected"),
    [("本命雷達測驗", True), ("本命雷達:0:女團", True), ("每日 MV", True), ("我喜歡小鹿", False)],
)
def test_is_fixed_command_looks_only_at_text(message: str, expected: bool) -> None:
    assert is_fixed_command(message) is expected


def test_artist_hint_routes_to_artist_report() -> None:
    context = MessageContext(text="", user_id="u", artist_hint="aespa")

    assert build_bot(make_deps()).dispatcher.resolve(context).name == "artist_report"


def test_line_renderer_sends_card_only_by_default() -> None:
    messages = build_line_messages(Reply(report="r", flex=_bubble(), alt_text="alt"))

    assert [message.to_dict()["type"] for message in messages] == ["flex"]
    assert messages[0].alt_text == "alt"


def test_line_renderer_sends_text_then_card_when_text_first() -> None:
    reply = Reply(report="hello", flex=_bubble(), alt_text="alt", text_first=True)

    messages = build_line_messages(reply)

    assert [message.to_dict()["type"] for message in messages] == ["text", "flex"]
    assert messages[0].text == "hello"


def test_line_renderer_attaches_quick_replies_to_text() -> None:
    reply = Reply(
        report="pick one",
        quick_replies=(
            QuickReplyAction(label="A", text="choose A"),
            QuickReplyAction(label="B", text="action=b", postback=True),
        ),
    )

    (message,) = build_line_messages(reply)
    actions = [item["action"] for item in message.to_dict()["quickReply"]["items"]]

    assert actions[0] == {"type": "message", "label": "A", "text": "choose A"}
    assert actions[1]["type"] == "postback"
    assert actions[1]["data"] == "action=b"


def test_line_renderer_falls_back_to_alt_text_for_invalid_flex() -> None:
    (message,) = build_line_messages(Reply(report="r", flex={"type": "nonsense"}, alt_text="alt"))

    assert message.to_dict() == {"type": "text", "text": "alt"}


def test_reply_text_prefers_fallback_text_and_json_omits_it() -> None:
    reply = Reply(report="report", fallback_text="fallback", cache={"type": "x"})

    assert reply.text == "fallback"
    assert reply.to_json() == {"report": "report", "flex": None, "cache": {"type": "x"}}


def _bubble() -> dict:
    return {
        "type": "bubble",
        "body": {"type": "box", "layout": "vertical", "contents": [{"type": "text", "text": "x"}]},
    }
