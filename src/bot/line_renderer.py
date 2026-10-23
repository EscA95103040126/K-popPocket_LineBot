from __future__ import annotations

import logging

from linebot.v3.messaging import (
    FlexContainer,
    FlexMessage,
    MessageAction,
    PostbackAction,
    QuickReply,
    QuickReplyItem,
    TextMessage,
)

from src.bot.reply import QuickReplyAction, Reply

logger = logging.getLogger(__name__)


def build_line_messages(reply: Reply) -> list:
    """Render a Reply as LINE messages: optional text (with quick replies) then the card."""
    messages = []
    if reply.flex is None or reply.text_first:
        messages.append(
            TextMessage(text=reply.text, quickReply=build_quick_reply(reply.quick_replies))
        )
    if reply.flex is not None:
        messages.append(build_flex_message(reply.flex, alt_text=reply.alt_text))
    return messages


def build_flex_message(flex_contents: dict, alt_text: str):
    try:
        return FlexMessage(altText=alt_text, contents=FlexContainer.from_dict(flex_contents))
    except Exception:
        logger.exception("Flex build failed; falling back to text.")
        return TextMessage(text=alt_text)


def build_quick_reply(actions: tuple[QuickReplyAction, ...]) -> QuickReply | None:
    if not actions:
        return None
    return QuickReply(
        items=[QuickReplyItem(action=_quick_reply_action(action)) for action in actions]
    )


def _quick_reply_action(action: QuickReplyAction):
    if action.postback:
        return PostbackAction(label=action.label, data=action.text)
    return MessageAction(label=action.label, text=action.text)
