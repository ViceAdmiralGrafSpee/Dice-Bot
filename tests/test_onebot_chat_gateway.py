from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.chat.platform.onebot.chat_gateway import handle_onebot_chat_event
from src.chat.platform.onebot.request_context import OneBotRequestContext


def _group_event(*, mentioned: bool = True) -> dict:
    message = []
    if mentioned:
        message.append({"type": "at", "data": {"qq": "90001"}})
    message.append({"type": "text", "data": {"text": " hello"}})
    return {
        "self_id": "90001",
        "post_type": "message",
        "message_type": "group",
        "message_id": "30003",
        "group_id": "20002",
        "user_id": "10001",
        "sender": {"nickname": "Player"},
        "message": message,
    }


@pytest.mark.asyncio
async def test_routes_addressed_message_through_shared_chat_core() -> None:
    sender = AsyncMock()
    chat_core = SimpleNamespace(
        should_process_message=AsyncMock(return_value=True),
        handle_chat_message=AsyncMock(
            return_value=SimpleNamespace(content="Core response")
        ),
    )

    handled = await handle_onebot_chat_event(sender, _group_event(), chat_core)

    assert handled is True
    request = chat_core.should_process_message.await_args.args[0]
    assert isinstance(request, OneBotRequestContext)
    assert request.message.platform == "qq"
    assert request.message.text == "hello"
    chat_core.handle_chat_message.assert_awaited_once_with(request)
    sender.send_message.assert_awaited_once_with(
        _group_event(),
        "Core response",
    )


@pytest.mark.asyncio
async def test_ignores_group_message_without_bot_mention() -> None:
    sender = AsyncMock()
    chat_core = SimpleNamespace(
        should_process_message=AsyncMock(),
        handle_chat_message=AsyncMock(),
    )

    handled = await handle_onebot_chat_event(
        sender,
        _group_event(mentioned=False),
        chat_core,
    )

    assert handled is False
    chat_core.should_process_message.assert_not_awaited()
    chat_core.handle_chat_message.assert_not_awaited()
    sender.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_does_not_generate_when_core_precheck_rejects_message() -> None:
    sender = AsyncMock()
    chat_core = SimpleNamespace(
        should_process_message=AsyncMock(return_value=False),
        handle_chat_message=AsyncMock(),
    )

    handled = await handle_onebot_chat_event(sender, _group_event(), chat_core)

    assert handled is False
    chat_core.handle_chat_message.assert_not_awaited()
    sender.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_request_context_uses_platform_neutral_defaults_and_tools() -> None:
    event = _group_event()
    sender = AsyncMock()
    captured_request = None

    def request_factory(message):
        nonlocal captured_request
        captured_request = OneBotRequestContext(message=message)
        return captured_request

    chat_core = SimpleNamespace(
        should_process_message=AsyncMock(return_value=True),
        handle_chat_message=AsyncMock(return_value=None),
    )

    assert await handle_onebot_chat_event(
        sender,
        event,
        chat_core,
        request_factory=request_factory,
    )
    assert await captured_request.get_effective_chat_config() == {
        "is_chat_enabled": True
    }
    assert await captured_request.get_formatted_history() == []

    tool_service = SimpleNamespace(execute_tool_call=AsyncMock(return_value="ok"))
    result = await captured_request.execute_tool_call(
        tool_service,
        {"name": "search", "arguments": {}},
        user_id="10001",
    )

    assert result == "ok"
    tool_service.execute_tool_call.assert_awaited_once_with(
        {"name": "search", "arguments": {}},
        channel=None,
        user_id="10001",
    )
