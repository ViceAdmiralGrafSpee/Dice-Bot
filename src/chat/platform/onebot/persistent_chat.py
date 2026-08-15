"""Persist every QQ message and route addressed ones through the chat core."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from contextlib import contextmanager
from typing import Any

from src.chat.actions import ActionContext
from src.chat.commands import CommandRegistry, CommandResult
from src.chat.dice.gate import (
    DiceCategoryGate,
    QQ_SENDER_ROLE,
    is_dice_category_command,
)
from src.chat.memory import SQLiteConversationRepository
from src.chat.platform import ConversationKind, MessageFileProvider
from src.config import BOT_NAME

from .chat_gateway import ChatCore, OneBotMessageSender, handle_onebot_chat_event
from .event_mapper import (
    is_bot_addressed,
    is_supported_message_event,
    map_onebot_message,
)
from .request_context import OneBotRequestContext
from .file_transfer import RecentMessageFileStore


TextRouter = Callable[
    [str, ActionContext],
    Awaitable[CommandResult | None],
]


@contextmanager
def _qq_sender_role(role: str | None):
    """Expose the QQ group role to the dicecmd control command."""
    token = QQ_SENDER_ROLE.set(role)
    try:
        yield
    finally:
        QQ_SENDER_ROLE.reset(token)


async def handle_persistent_onebot_chat_event(
    sender: OneBotMessageSender,
    event: Mapping[str, Any],
    chat_core: ChatCore,
    repository: SQLiteConversationRepository,
    command_registry: CommandRegistry,
    *,
    file_provider: MessageFileProvider | None = None,
    recent_files: RecentMessageFileStore | None = None,
    text_router: TextRouter | None = None,
    dice_gate: DiceCategoryGate | None = None,
) -> bool:
    """Record supported messages, while generating only when addressed."""

    if not is_supported_message_event(event):
        return False

    incoming = map_onebot_message(event)
    await repository.record_incoming(incoming)
    if recent_files is not None:
        recent_files.remember(incoming)

    async def record_response(message, content: str) -> None:
        await repository.record_assistant_reply(
            message,
            content,
            bot_id=str(event.get("self_id", "")),
            bot_name=BOT_NAME,
        )

    # OneBot v11 sender role: ``owner`` (群主) / ``admin`` (群管理员) / member.
    # The event payload is a Mapping; avoid rebinding the ``sender`` argument
    # (the OneBotMessageSender used to reply) on the event nested dict.
    event_sender = event.get("sender")
    sender_role = None
    if isinstance(event_sender, Mapping):
        role = event_sender.get("role")
        sender_role = str(role) if role not in (None, "") else None

    context_files = incoming.files
    if not context_files and recent_files is not None:
        context_files = recent_files.latest(incoming)
    action_context = ActionContext(
        user_id=incoming.user_id,
        user_name=incoming.user_name,
        platform=incoming.platform,
        message_id=incoming.message_id,
        conversation_id=incoming.conversation.conversation_id,
        files=context_files,
        file_provider=file_provider,
    )

    # The QQ group role stays inside the OneBot adapter boundary: it is only
    # visible to the QQ-only ``.dicecmd`` control command via a context
    # variable, and is never part of the platform-neutral ActionContext.
    with _qq_sender_role(sender_role):
        # Silently consume traditional dice commands when the group switch is
        # off. Private conversations and LLM tool calls (.dicecmd /
        # roll_dice / dnd5e_check live outside this category) are never
        # affected.
        if (
            dice_gate is not None
            and incoming.conversation.kind is ConversationKind.GROUP
            and is_dice_category_command(incoming.text, command_registry)
            and not await dice_gate.is_enabled(
                incoming.conversation.conversation_id
            )
        ):
            return True

        command_result = (
            await text_router(incoming.text, action_context)
            if text_router is not None
            else None
        )
        if command_result is None:
            command_result = await command_registry.dispatch(
                incoming.text,
                action_context,
            )
        if command_result is not None:
            await sender.send_message(event, command_result.content)
            await record_response(incoming, command_result.content)
            return True

    if (
        incoming.conversation.kind is ConversationKind.DIRECT
        and not incoming.text
        and any(file.name.lower().endswith(".xlsx") for file in incoming.files)
    ):
        instruction = "已收到 XLSX 文件。请在 5 分钟内发送：.pc import"
        await sender.send_message(event, instruction)
        await record_response(incoming, instruction)
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
