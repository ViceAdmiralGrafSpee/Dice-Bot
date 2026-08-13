from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.chat.commands import CommandRegistry
from src.chat.dice import (
    DiceEngine,
    DiceExpressionError,
    handle_dice_command,
    register_dice_commands,
)
from src.chat.memory import SQLiteConversationRepository
from src.chat.platform.onebot.event_mapper import map_onebot_message
from src.chat.platform.onebot.persistent_chat import (
    handle_persistent_onebot_chat_event,
)


def _fixed_engine(*values: int) -> DiceEngine:
    rolls = iter(values)
    return DiceEngine(roll_die=lambda _sides: next(rolls))


def _dice_registry(*values: int) -> CommandRegistry:
    registry = CommandRegistry()
    register_dice_commands(registry, _fixed_engine(*values))
    return registry


def _group_event(text: str, *, message_id: str = "30003") -> dict:
    return {
        "self_id": "90001",
        "post_type": "message",
        "message_type": "group",
        "message_id": message_id,
        "group_id": "20002",
        "user_id": "10001",
        "sender": {"nickname": "调查员"},
        "message": [{"type": "text", "data": {"text": text}}],
    }


def test_rolls_each_die_and_applies_modifier() -> None:
    result = _fixed_engine(4, 2).roll("2d6 + 3")

    assert result.notation == "2d6+3"
    assert result.rolls == (4, 2)
    assert result.total == 9
    assert result.format() == "🎲 2d6+3 = [4, 2] + 3 = 9"


def test_defaults_missing_dice_count_to_one() -> None:
    result = _fixed_engine(17).roll("d20-1")

    assert result.notation == "1d20-1"
    assert result.total == 16


@pytest.mark.parametrize(
    "expression",
    ["0d6", "101d6", "1d1", "1d100001", "2d6+1000001", "2d6; rm -rf"],
)
def test_rejects_invalid_or_unbounded_expressions(expression: str) -> None:
    with pytest.raises(DiceExpressionError):
        DiceEngine().roll(expression)


def test_command_boundary_distinguishes_dice_from_ordinary_text() -> None:
    assert handle_dice_command(".r", DiceEngine()) == (
        "骰子命令格式：.r 1d100 或 .r 2d6+3"
    )
    assert handle_dice_command(".r 0d6", DiceEngine()).startswith("骰子命令有误")
    assert handle_dice_command(".random chat", DiceEngine()) is None


@pytest.mark.parametrize(
    ("text", "rolls", "expected"),
    [
        (".r 1d100", (73,), "🎲 1d100 = [73] = 73"),
        (".r 2d6+3", (4, 2), "🎲 2d6+3 = [4, 2] + 3 = 9"),
    ],
)
def test_registered_roll_command_preserves_existing_examples(
    text: str,
    rolls: tuple[int, ...],
    expected: str,
) -> None:
    result = _dice_registry(*rolls).dispatch(text)

    assert result is not None
    assert result.content == expected


@pytest.mark.asyncio
async def test_group_dice_command_bypasses_llm_and_records_result(tmp_path) -> None:
    repository = SQLiteConversationRepository(tmp_path / "memory.sqlite3")
    await repository.initialize()
    sender = AsyncMock()
    chat_core = SimpleNamespace(
        should_process_message=AsyncMock(),
        handle_chat_message=AsyncMock(),
    )
    event = _group_event(".r 2d6+3")

    handled = await handle_persistent_onebot_chat_event(
        sender,
        event,
        chat_core,
        repository,
        _dice_registry(4, 2),
    )

    assert handled is True
    sender.send_message.assert_awaited_once_with(
        event,
        "🎲 2d6+3 = [4, 2] + 3 = 9",
    )
    chat_core.should_process_message.assert_not_awaited()
    chat_core.handle_chat_message.assert_not_awaited()

    incoming = map_onebot_message(event)
    stored = await repository.get_recent_messages(incoming)
    assert [message.role for message in stored] == ["user", "assistant"]
    assert stored[-1].content.endswith("= 9")


@pytest.mark.asyncio
async def test_non_command_continues_through_existing_chat_flow(tmp_path) -> None:
    repository = SQLiteConversationRepository(tmp_path / "memory.sqlite3")
    await repository.initialize()
    sender = AsyncMock()
    chat_core = SimpleNamespace(
        should_process_message=AsyncMock(return_value=True),
        handle_chat_message=AsyncMock(
            return_value=SimpleNamespace(content="聊天回复")
        ),
    )
    event = _group_event("普通聊天")
    event["message"].insert(0, {"type": "at", "data": {"qq": "90001"}})

    handled = await handle_persistent_onebot_chat_event(
        sender,
        event,
        chat_core,
        repository,
        _dice_registry(),
    )

    assert handled is True
    chat_core.should_process_message.assert_awaited_once()
    chat_core.handle_chat_message.assert_awaited_once()
    sender.send_message.assert_awaited_once_with(event, "聊天回复")
