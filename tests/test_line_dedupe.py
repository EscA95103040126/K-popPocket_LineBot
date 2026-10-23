from types import SimpleNamespace

from src.bot.line_events import LineEventGuard, _line_event_id


def _event(event_id: str, user_id: str = "user-1"):
    return SimpleNamespace(
        webhook_event_id=event_id,
        source=SimpleNamespace(user_id=user_id),
    )


def test_line_event_id_supports_sdk_snake_case() -> None:
    assert _line_event_id(_event("event-1")) == "event-1"


def test_line_event_dedupe_skips_processed_event(tmp_path) -> None:
    guard = LineEventGuard(tmp_path / "seen.json")
    event = _event("event-1")

    assert guard.should_skip_line_event(event, "每日 MV") is False
    guard.mark_line_event_processed(event)
    assert guard.should_skip_line_event(event, "每日 MV") is True


def test_line_event_dedupe_survives_process_restart(tmp_path) -> None:
    event = _event("event-1")
    first_process = LineEventGuard(tmp_path / "seen.json")
    assert first_process.should_skip_line_event(event, "每日 MV") is False
    first_process.mark_line_event_processed(event)

    restarted_process = LineEventGuard(tmp_path / "seen.json")

    assert restarted_process.should_skip_line_event(event, "每日 MV") is True


def test_line_event_dedupe_writes_cache_atomically(tmp_path) -> None:
    cache_path = tmp_path / "seen.json"
    guard = LineEventGuard(cache_path)

    event = _event("event-atomic")
    assert guard.should_skip_line_event(event, "每日 MV") is False
    guard.mark_line_event_processed(event)

    assert cache_path.exists()
    assert not cache_path.with_name(f"{cache_path.name}.tmp").exists()


def test_line_message_debounce_skips_fast_duplicate(tmp_path) -> None:
    guard = LineEventGuard(tmp_path / "seen.json", monotonic=lambda: 100.0)

    assert guard.should_skip_line_event(_event("event-1"), "每日 MV") is False
    assert guard.should_skip_line_event(_event("event-2"), "每日 MV") is True


def test_line_message_debounce_allows_repeat_after_window(tmp_path) -> None:
    now = iter([100.0, 102.0])
    guard = LineEventGuard(tmp_path / "seen.json", monotonic=lambda: next(now))

    assert guard.should_skip_line_event(_event("event-1"), "每日 MV") is False
    assert guard.should_skip_line_event(_event("event-2"), "每日 MV") is False
