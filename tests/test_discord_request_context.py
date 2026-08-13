from unittest.mock import AsyncMock, Mock, patch

import discord
import pytest

from src.chat.platform import ConversationContext, ConversationKind, IncomingMessage
from src.chat.platform.discord import DiscordRequestContext


def _request_context():
    channel = Mock(spec=discord.TextChannel)
    channel.id = 30003

    guild = Mock(spec=discord.Guild)
    guild.id = 20002

    author = Mock(spec=discord.Member)
    author.id = 10001

    raw_message = Mock(spec=discord.Message)
    raw_message.id = 90009
    raw_message.channel = channel
    raw_message.guild = guild
    raw_message.author = author

    incoming = IncomingMessage(
        platform="discord",
        message_id="90009",
        user_id="10001",
        user_name="调查员",
        text="调查左边的门",
        conversation=ConversationContext(
            conversation_id="30003",
            kind=ConversationKind.CHANNEL,
            space_id="20002",
        ),
    )
    return DiscordRequestContext(message=incoming, raw_message=raw_message)


@pytest.mark.asyncio
async def test_discord_context_supplies_chat_settings():
    request = _request_context()
    expected = {"is_chat_enabled": True}

    with patch(
        "src.chat.platform.discord.request_context.chat_settings_service.get_effective_channel_config",
        new=AsyncMock(return_value=expected),
    ) as get_config:
        result = await request.get_effective_chat_config()

    assert result == expected
    get_config.assert_awaited_once_with(request.raw_message.channel)


@pytest.mark.asyncio
async def test_discord_context_supplies_formatted_history():
    request = _request_context()
    context_service = Mock()
    context_service.get_formatted_channel_history_new = AsyncMock(
        return_value=[{"role": "model", "parts": ["history"]}]
    )

    with patch(
        "src.chat.platform.discord.request_context.get_context_service",
        return_value=context_service,
    ):
        result = await request.get_formatted_history()

    assert result == [{"role": "model", "parts": ["history"]}]
    context_service.get_formatted_channel_history_new.assert_awaited_once_with(
        30003,
        10001,
        20002,
        exclude_message_id=90009,
    )


@pytest.mark.asyncio
async def test_discord_context_keeps_raw_channel_inside_tool_execution():
    request = _request_context()
    tool_service = Mock()
    tool_service.execute_tool_call = AsyncMock(return_value="tool-result")

    result = await request.execute_tool_call(
        tool_service,
        {"name": "search", "arguments": {}},
        user_id=10001,
        user_name="调查员",
    )

    assert result == "tool-result"
    tool_service.execute_tool_call.assert_awaited_once_with(
        {"name": "search", "arguments": {}},
        channel=request.raw_message.channel,
        user_id=10001,
        user_name="调查员",
    )
