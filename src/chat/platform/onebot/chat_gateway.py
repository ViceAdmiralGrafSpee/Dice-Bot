"""Route addressed OneBot messages through the platform-neutral chat boundary."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any, Protocol

from src.chat.platform import IncomingMessage, PlatformRequestContext

from .event_mapper import is_bot_addressed, map_onebot_message
from .request_context import OneBotRequestContext


class ChatResultLike(Protocol):
    content: str


class ChatCore(Protocol):
    async def should_process_message(
        self, request: PlatformRequestContext
    ) -> bool: ...

    async def handle_chat_message(
        self, request: PlatformRequestContext
    ) -> ChatResultLike | None: ...


class OneBotMessageSender(Protocol):
    async def send_message(self, event: Mapping[str, Any], text: str) -> None: ...


RequestFactory = Callable[[IncomingMessage], PlatformRequestContext]
ResponseRecorder = Callable[[IncomingMessage, str], Awaitable[None]]


async def handle_onebot_chat_event(
    sender: OneBotMessageSender,
    event: Mapping[str, Any],
    chat_core: ChatCore,
    *,
    request_factory: RequestFactory = OneBotRequestContext,
    response_recorder: ResponseRecorder | None = None,
) -> bool:
    """Send one addressed OneBot event through the shared chat core.

    ``False`` means the event was ignored or rejected before generation.
    ``True`` means the core accepted the event, even when it chose not to return
    text. Keeping sending outside ``ChatService`` preserves the platform split.
    """

    if not is_bot_addressed(event):
        return False

    request = request_factory(map_onebot_message(event))
    if not await chat_core.should_process_message(request):
        return False

    result = await chat_core.handle_chat_message(request)
    if result is not None and result.content:
        await sender.send_message(event, result.content)
        if response_recorder is not None:
            await response_recorder(request.message, result.content)

    return True
