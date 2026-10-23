from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from src.bot.reply import Reply

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MessageContext:
    text: str
    user_id: str
    artist_hint: str = ""


Matcher = Callable[[MessageContext], bool]
Responder = Callable[[MessageContext], Reply]


@dataclass(frozen=True)
class Handler:
    name: str
    matches: Matcher
    respond: Responder


class Dispatcher:
    """Ordered first-match routing table shared by every channel adapter."""

    def __init__(self, handlers: Sequence[Handler], fallback: Handler) -> None:
        names = [handler.name for handler in (*handlers, fallback)]
        duplicates = {name for name in names if names.count(name) > 1}
        if duplicates:
            raise ValueError(f"Duplicate handler names: {sorted(duplicates)}")
        self.handlers = tuple(handlers)
        self.fallback = fallback

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(handler.name for handler in self.handlers) + (self.fallback.name,)

    def resolve(self, context: MessageContext) -> Handler:
        for handler in self.handlers:
            if handler.matches(context):
                return handler
        return self.fallback

    def dispatch(self, context: MessageContext) -> Reply:
        handler = self.resolve(context)
        logger.info("Dispatching message to handler %s", handler.name)
        return handler.respond(context)
