from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import TYPE_CHECKING, Callable, ContextManager, Iterator

from linebot.v3 import WebhookHandler
from linebot.v3.messaging import (
    ApiClient,
    Configuration,
    MessagingApi,
    ReplyMessageRequest,
    TextMessage,
)
from linebot.v3.webhooks import FollowEvent, MessageEvent, PostbackEvent, TextMessageContent

from src.bot.dispatcher import MessageContext
from src.bot.features.menus import welcome_text
from src.bot.line_events import line_user_id
from src.bot.line_renderer import build_line_messages

if TYPE_CHECKING:
    from src.bot.container import Bot
    from src.bot.line_events import LineEventGuard

logger = logging.getLogger(__name__)

MessagingApiFactory = Callable[[], ContextManager[MessagingApi]]


class LineAdapter:
    """Verifies LINE webhooks, routes events through the dispatcher and sends the replies."""

    def __init__(
        self,
        *,
        bot: Bot,
        channel_secret: str,
        access_token: str,
        events: LineEventGuard,
        messaging_api_factory: MessagingApiFactory | None = None,
    ) -> None:
        self.bot = bot
        self.events = events
        self.handler = WebhookHandler(channel_secret)
        configuration = Configuration(access_token=access_token)
        self.messaging_api_factory = messaging_api_factory or (
            lambda: _messaging_api(configuration)
        )
        # The SDK counts parameters with getfullargspec, which includes ``self`` for bound
        # methods and would make it pass (event, destination); register one-argument callables.
        self.handler.add(MessageEvent, message=TextMessageContent)(
            lambda event: self._handle_text_message(event)
        )
        self.handler.add(PostbackEvent)(lambda event: self._handle_postback(event))
        self.handler.add(FollowEvent)(lambda event: self._handle_follow(event))

    def handle(self, body: str, signature: str) -> None:
        """Raises linebot InvalidSignatureError when the signature does not match."""
        self.handler.handle(body, signature)

    def reply_to_event(self, event: object, user_text: str) -> None:
        if self.events.should_skip_line_event(event, user_text):
            return
        user_id = line_user_id(event) or "line-user"
        try:
            self.bot.features.pocket.ensure_kpop_radar_user(user_id)
        except Exception:
            logger.exception("Could not initialize K-pop Radar user.")
        reply = self.bot.dispatcher.dispatch(MessageContext(text=user_text, user_id=user_id))
        with self.messaging_api_factory() as line_bot_api:
            try:
                line_bot_api.reply_message(
                    ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=build_line_messages(reply),
                    )
                )
                self.events.mark_line_event_processed(event)
            except Exception as exc:
                logger.warning("Flex reply failed; retrying with text fallback: %s", exc)
                try:
                    line_bot_api.reply_message(
                        ReplyMessageRequest(
                            reply_token=event.reply_token,
                            messages=[TextMessage(text=reply.text)],
                        )
                    )
                    self.events.mark_line_event_processed(event)
                except Exception as fallback_exc:
                    self.events.clear_line_event_processing(event)
                    logger.exception("LINE reply failed: %s", fallback_exc)

    def _handle_text_message(self, event: MessageEvent) -> None:
        self.reply_to_event(event, event.message.text)

    def _handle_postback(self, event: PostbackEvent) -> None:
        self.reply_to_event(event, str(getattr(event.postback, "data", "")))

    def _handle_follow(self, event: FollowEvent) -> None:
        try:
            user_id = line_user_id(event) or "line-user"
            try:
                self.bot.features.pocket.ensure_kpop_radar_user(user_id)
            except Exception:
                logger.exception("Could not initialize K-pop Radar user on follow.")
            with self.messaging_api_factory() as line_bot_api:
                line_bot_api.reply_message(
                    ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[TextMessage(text=welcome_text())],
                    )
                )
        except Exception:
            logger.exception("Welcome reply failed.")


@contextmanager
def _messaging_api(configuration: Configuration) -> Iterator[MessagingApi]:
    with ApiClient(configuration) as api_client:
        yield MessagingApi(api_client)
