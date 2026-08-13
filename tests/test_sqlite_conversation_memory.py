from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.chat.memory import SQLiteConversationRepository
from src.chat.platform.onebot.event_mapper import map_onebot_message
from src.chat.platform.onebot.persistent_chat import (
    handle_persistent_onebot_chat_event,
)


def _group_event(
    message_id: str,
    text: str,
    *,
    group_id: str = "20002",
    user_id: str = "10001",
    user_name: str = "调查员",
    mentioned: bool = False,
) -> dict:
    message = []
    if mentioned:
        message.append({"type": "at", "data": {"qq": "90001"}})
    message.append({"type": "text", "data": {"text": text}})
    return {
        "self_id": "90001",
        "post_type": "message",
        "message_type": "group",
        "message_id": message_id,
        "group_id": group_id,
        "user_id": user_id,
        "sender": {"nickname": user_name},
        "message": message,
    }


@pytest.mark.asyncio
async def test_messages_survive_repository_restart_and_stay_in_their_group(
    tmp_path,
) -> None:
    db_path = tmp_path / "memory.sqlite3"
    repository = SQLiteConversationRepository(db_path)
    await repository.initialize()
    first = map_onebot_message(_group_event("1", "先检查门窗"))
    other_group = map_onebot_message(
        _group_event("2", "这是另一个团", group_id="99999")
    )
    await repository.record_incoming(first)
    await repository.record_incoming(other_group)

    reopened_repository = SQLiteConversationRepository(db_path)
    await reopened_repository.initialize()
    messages = await reopened_repository.get_recent_messages(first)

    assert [message.content for message in messages] == ["先检查门窗"]


@pytest.mark.asyncio
async def test_non_mentioned_group_messages_become_context_without_triggering_ai(
    tmp_path,
) -> None:
    repository = SQLiteConversationRepository(tmp_path / "memory.sqlite3")
    await repository.initialize()
    sender = AsyncMock()
    chat_core = SimpleNamespace(
        should_process_message=AsyncMock(return_value=True),
        handle_chat_message=AsyncMock(
            return_value=SimpleNamespace(content="门窗已经检查过了。")
        ),
    )
    background_event = _group_event("1", "我先检查了门窗")

    handled = await handle_persistent_onebot_chat_event(
        sender,
        background_event,
        chat_core,
        repository,
    )

    assert handled is False
    chat_core.should_process_message.assert_not_awaited()

    addressed_event = _group_event("2", "刚才检查了什么？", mentioned=True)
    handled = await handle_persistent_onebot_chat_event(
        sender,
        addressed_event,
        chat_core,
        repository,
    )

    assert handled is True
    request = chat_core.handle_chat_message.await_args.args[0]
    history = await request.get_formatted_history()
    serialized_history = repr(history)
    assert "我先检查了门窗" in serialized_history
    assert "刚才检查了什么" not in serialized_history
    sender.send_message.assert_awaited_once_with(
        addressed_event,
        "门窗已经检查过了。",
    )

    stored = await repository.get_recent_messages(request.message)
    assert [message.role for message in stored] == ["user", "user", "assistant"]
    assert stored[-1].content == "门窗已经检查过了。"


@pytest.mark.asyncio
async def test_storage_limit_prevents_unbounded_raw_history(tmp_path) -> None:
    repository = SQLiteConversationRepository(
        tmp_path / "memory.sqlite3",
        context_limit=2,
        storage_limit=3,
    )
    await repository.initialize()
    latest = None
    for index in range(5):
        latest = map_onebot_message(_group_event(str(index), f"消息 {index}"))
        await repository.record_incoming(latest)

    stored = await repository.get_recent_messages(latest)

    assert [message.content for message in stored] == ["消息 3", "消息 4"]
