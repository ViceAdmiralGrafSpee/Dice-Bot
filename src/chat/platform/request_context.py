"""Operations the chat core needs from a messaging platform."""

from __future__ import annotations

from typing import Any, Protocol

from .models import IncomingMessage


class PlatformRequestContext(Protocol):
    """A platform message plus the few platform operations used by chat."""

    message: IncomingMessage

    async def get_effective_chat_config(self) -> dict[str, Any]: ...

    async def get_formatted_history(self) -> list[dict[str, Any]]: ...

    async def execute_tool_call(
        self,
        tool_service: Any,
        tool_call: Any,
        **kwargs: Any,
    ) -> Any: ...
