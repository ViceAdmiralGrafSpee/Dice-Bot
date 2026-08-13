from unittest.mock import AsyncMock

import pytest

from src.chat.platform.onebot.echo_bot import ECHO_RESPONSE, handle_echo_event
from src.chat.platform.onebot.transport import build_send_message_action


def test_builds_group_send_action_with_string_id() -> None:
    action = build_send_message_action(
        {"message_type": "group", "group_id": 20002},
        "收到",
        echo="test-echo",
    )

    assert action == {
        "action": "send_group_msg",
        "params": {
            "group_id": "20002",
            "message": [{"type": "text", "data": {"text": "收到"}}],
        },
        "echo": "test-echo",
    }


def test_builds_private_send_action_with_string_id() -> None:
    action = build_send_message_action(
        {"message_type": "private", "user_id": 10001},
        "收到",
        echo="test-echo",
    )

    assert action["action"] == "send_private_msg"
    assert action["params"]["user_id"] == "10001"


@pytest.mark.asyncio
async def test_echo_handler_replies_to_addressed_group_message() -> None:
    client = AsyncMock()
    event = {
        "self_id": "90001",
        "post_type": "message",
        "message_type": "group",
        "message_id": "30003",
        "group_id": "20002",
        "user_id": "10001",
        "sender": {"nickname": "调查员"},
        "message": [
            {"type": "at", "data": {"qq": "90001"}},
            {"type": "text", "data": {"text": "测试"}},
        ],
    }

    assert await handle_echo_event(client, event) is True
    client.send_message.assert_awaited_once_with(event, ECHO_RESPONSE)


@pytest.mark.asyncio
async def test_echo_handler_ignores_unmentioned_group_message() -> None:
    client = AsyncMock()
    event = {
        "self_id": "90001",
        "post_type": "message",
        "message_type": "group",
        "message_id": "30003",
        "group_id": "20002",
        "user_id": "10001",
        "sender": {"nickname": "调查员"},
        "message": [{"type": "text", "data": {"text": "普通聊天"}}],
    }

    assert await handle_echo_event(client, event) is False
    client.send_message.assert_not_awaited()
