"""Discord implementation of the operations required by the chat core."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import discord

from src.chat.features.chat_settings.services.chat_settings_service import (
    chat_settings_service,
)
from src.chat.platform.models import IncomingMessage
from src.chat.services.context_service_test import get_context_service


@dataclass(slots=True)
class DiscordRequestContext:
    """Keep the raw Discord object outside the platform-independent core."""

    message: IncomingMessage
    raw_message: discord.Message

    async def get_effective_chat_config(self) -> dict[str, Any]:
        if isinstance(self.raw_message.channel, discord.abc.GuildChannel):
            return await chat_settings_service.get_effective_channel_config(
                self.raw_message.channel
            )
        return {}

    async def get_formatted_history(self) -> list[dict[str, Any]]:
        guild_id = self.raw_message.guild.id if self.raw_message.guild else 0
        return await get_context_service().get_formatted_channel_history_new(
            self.raw_message.channel.id,
            self.raw_message.author.id,
            guild_id,
            exclude_message_id=self.raw_message.id,
        )

    async def execute_tool_call(
        self,
        tool_service: Any,
        tool_call: Any,
        **kwargs: Any,
    ) -> Any:
        return await tool_service.execute_tool_call(
            tool_call,
            channel=self.raw_message.channel,
            **kwargs,
        )
