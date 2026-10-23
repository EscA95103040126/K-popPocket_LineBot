from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.utils.response_formatter import fit_line_text


@dataclass(frozen=True)
class QuickReplyAction:
    label: str
    text: str
    postback: bool = False


@dataclass(frozen=True)
class Reply:
    """Channel-agnostic bot reply. Adapters decide how to render each field.

    report: canonical text body (JSON ``report`` field).
    flex: LINE Flex contents, rendered as a card when the channel supports it.
    alt_text: notification / accessibility text for the Flex card.
    fallback_text: text shown when the card cannot be shown; defaults to ``report``.
    text_first: send the text before the card instead of the card alone.
    quick_replies: quick reply buttons attached to the text message.
    cache: cache metadata exposed by the JSON API.
    """

    report: str
    flex: dict[str, Any] | None = None
    alt_text: str = ""
    fallback_text: str | None = None
    text_first: bool = False
    quick_replies: tuple[QuickReplyAction, ...] = field(default_factory=tuple)
    cache: dict[str, Any] | None = None

    @property
    def text(self) -> str:
        return fit_line_text(self.report if self.fallback_text is None else self.fallback_text)

    def to_json(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"report": self.report, "flex": self.flex}
        if self.cache is not None:
            payload["cache"] = self.cache
        return payload
