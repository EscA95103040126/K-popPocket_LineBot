from __future__ import annotations

import json
import logging
from collections import OrderedDict
from collections.abc import Callable
from pathlib import Path
from threading import RLock
from time import monotonic, time

logger = logging.getLogger(__name__)


LINE_EVENT_DEDUPE_TTL_SECONDS = 60 * 60 * 24
LINE_EVENT_DEDUPE_MAX_SIZE = 1000
LINE_MESSAGE_DEBOUNCE_SECONDS = 1.5


def _line_event_id(event: object) -> str:
    for attr_name in ("webhook_event_id", "webhookEventId"):
        value = getattr(event, attr_name, "")
        if value:
            return str(value)
    return ""


def _line_message_key(event: object, user_text: str) -> tuple[str, str] | None:
    source_id = line_user_id(event)
    if not source_id:
        return None
    return source_id, user_text.strip()


def line_user_id(event: object) -> str:
    source = getattr(event, "source", None)
    return str(
        getattr(source, "user_id", "")
        or getattr(source, "group_id", "")
        or getattr(source, "room_id", "")
    )


def _prune_ordered_timestamps(
    timestamps: OrderedDict,
    *,
    now: float,
    ttl_seconds: float,
    max_size: int,
) -> None:
    expired_keys = [
        key
        for key, timestamp in timestamps.items()
        if now - float(timestamp) > ttl_seconds
    ]
    for key in expired_keys:
        timestamps.pop(key, None)

    while len(timestamps) > max_size:
        timestamps.popitem(last=False)


class LineEventGuard:
    """Drops LINE webhook redeliveries and fast duplicate taps from the same user."""

    def __init__(
        self,
        dedupe_path: Path,
        clock: Callable[[], float] = time,
        monotonic: Callable[[], float] = monotonic,
    ) -> None:
        self.dedupe_path = dedupe_path
        self.clock = clock
        self.monotonic = monotonic
        self.line_processed_event_ids: OrderedDict[str, float] | None = None
        self.line_processing_event_ids: set[str] = set()
        self.line_recent_message_keys: OrderedDict[tuple[str, str], float] = OrderedDict()
        self.line_event_dedupe_lock = RLock()

    def should_skip_line_event(self, event: object, user_text: str) -> bool:
        event_id = _line_event_id(event)
        if event_id and self.is_line_event_processed_or_processing(event_id):
            logger.info("Skipping duplicate LINE webhook event: %s", event_id)
            return True

        if self.is_line_message_debounced(event, user_text):
            logger.info("Skipping debounced LINE message: %s", user_text)
            if event_id:
                self.line_processing_event_ids.discard(event_id)
            return True

        return False

    def is_line_event_processed_or_processing(self, event_id: str) -> bool:
        with self.line_event_dedupe_lock:
            if event_id in self.line_processing_event_ids:
                return True

            processed_event_ids = self._line_processed_event_ids()
            now = self.clock()
            _prune_ordered_timestamps(
                processed_event_ids,
                now=now,
                ttl_seconds=LINE_EVENT_DEDUPE_TTL_SECONDS,
                max_size=LINE_EVENT_DEDUPE_MAX_SIZE,
            )
            if event_id in processed_event_ids:
                processed_event_ids.move_to_end(event_id)
                return True

            self.line_processing_event_ids.add(event_id)
            return False

    def mark_line_event_processed(self, event: object) -> None:
        event_id = _line_event_id(event)
        if not event_id:
            return

        with self.line_event_dedupe_lock:
            processed_event_ids = self._line_processed_event_ids()
            processed_event_ids[event_id] = self.clock()
            _prune_ordered_timestamps(
                processed_event_ids,
                now=processed_event_ids[event_id],
                ttl_seconds=LINE_EVENT_DEDUPE_TTL_SECONDS,
                max_size=LINE_EVENT_DEDUPE_MAX_SIZE,
            )
            self.line_processing_event_ids.discard(event_id)
            self._save_line_processed_event_ids(processed_event_ids)

    def clear_line_event_processing(self, event: object) -> None:
        event_id = _line_event_id(event)
        if event_id:
            with self.line_event_dedupe_lock:
                self.line_processing_event_ids.discard(event_id)

    def _line_processed_event_ids(self) -> OrderedDict[str, float]:
        with self.line_event_dedupe_lock:
            if self.line_processed_event_ids is not None:
                return self.line_processed_event_ids

            self.line_processed_event_ids = OrderedDict()
            if not self.dedupe_path.exists():
                return self.line_processed_event_ids

            try:
                raw_event_ids = json.loads(self.dedupe_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                logger.warning("Could not read LINE event dedupe cache; starting fresh.")
                return self.line_processed_event_ids

            if not isinstance(raw_event_ids, dict):
                return self.line_processed_event_ids

            for event_id, timestamp in raw_event_ids.items():
                try:
                    self.line_processed_event_ids[str(event_id)] = float(timestamp)
                except (TypeError, ValueError):
                    continue
            return self.line_processed_event_ids

    def _save_line_processed_event_ids(self, event_ids: OrderedDict[str, float]) -> None:
        try:
            self.dedupe_path.parent.mkdir(parents=True, exist_ok=True)
            temp_path = self.dedupe_path.with_name(f"{self.dedupe_path.name}.tmp")
            temp_path.write_text(
                json.dumps(event_ids, ensure_ascii=False),
                encoding="utf-8",
            )
            temp_path.replace(self.dedupe_path)
        except OSError:
            logger.warning("Could not write LINE event dedupe cache.", exc_info=True)

    def is_line_message_debounced(self, event: object, user_text: str) -> bool:
        key = _line_message_key(event, user_text)
        if key is None:
            return False

        now = self.monotonic()
        _prune_ordered_timestamps(
            self.line_recent_message_keys,
            now=now,
            ttl_seconds=LINE_MESSAGE_DEBOUNCE_SECONDS,
            max_size=200,
        )
        if key in self.line_recent_message_keys:
            self.line_recent_message_keys[key] = now
            self.line_recent_message_keys.move_to_end(key)
            return True

        self.line_recent_message_keys[key] = now
        return False
