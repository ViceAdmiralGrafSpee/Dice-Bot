"""OneBot implementation of the operations required by the chat core."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.chat.platform.models import IncomingMessage


@dataclass(slots=True)
class OneBotRequestContext:
    """Keep OneBot-specific defaults outside the platform-independent core.

    History and per-conversation settings are deliberately plain values for now.
    A later adapter step can populate them from OneBot APIs or persistent storage
    without changing ``ChatService``.
    """

    message: IncomingMessage
    effective_chat_config: dict[str, Any] = field(
        default_factory=lambda: {"is_chat_enabled": True}
    )
    formatted_history: list[dict[str, Any]] = field(default_factory=list)

    async def get_effective_chat_config(self) -> dict[str, Any]:
        return dict(self.effective_chat_config)

    async def get_formatted_history(self) -> list[dict[str, Any]]:
        return list(self.formatted_history)

    async def execute_tool_call(
        self,
        tool_service: Any,
        tool_call: Any,
        **kwargs: Any,
    ) -> Any:
        # The existing tool layer still accepts an optional Discord channel.
        # Passing None keeps platform-neutral tools usable without inventing a
        # fake Discord object. Platform-specific tools can be separated later.
        return await tool_service.execute_tool_call(
            tool_call,
            channel=None,
            **kwargs,
        )
