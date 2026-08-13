"""Persist every QQ message and route addressed ones through the chat core."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from src.chat.commands import CommandRegistry
from src.chat.memory import SQLiteConversationRepository
from src.config import BOT_NAME

from .chat_gateway import ChatCore, OneBotMessageSender, handle_onebot_chat_event
from .event_mapper import (
    is_bot_addressed,
    is_supported_message_event,
    map_onebot_message,
)
from .request_context import OneBotRequestContext


async def handle_persistent_onebot_chat_event(
    sender: OneBotMessageSender,
    event: Mapping[str, Any],
    chat_core: ChatCore,
    repository: SQLiteConversationRepository,
    command_registry: CommandRegistry,
) -> bool:
    """Record supported messages, while generating only when addressed."""

    if not is_supported_message_event(event):
        return False

    incoming = map_onebot_message(event)
    await repository.record_incoming(incoming)

    async def record_response(message, content: str) -> None:
        await repository.record_assistant_reply(
            message,
            content,
            bot_id=str(event.get("self_id", "")),
            bot_name=BOT_NAME,
        )

    command_result = command_registry.dispatch(incoming.text)
    if command_result is not None:
        await sender.send_message(event, command_result.content)
        await record_response(incoming, command_result.content)
        return True

    if not is_bot_addressed(event):
        return False

    request = OneBotRequestContext(
        message=incoming,
        history_provider=repository,
    )

    return await handle_onebot_chat_event(
        sender,
        event,
        chat_core,
        request_factory=lambda _message: request,
        response_recorder=record_response,
    )
