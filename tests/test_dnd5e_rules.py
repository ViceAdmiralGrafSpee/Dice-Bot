from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.chat.commands import CommandRegistry
from src.chat.memory import SQLiteConversationRepository
from src.chat.platform.onebot.persistent_chat import (
    handle_persistent_onebot_chat_event,
)
from src.chat.rules import RuleSystemRegistry
from src.chat.rules.dnd5e import D20RollMode, Dnd5eEngine, Dnd5eRuleSystem


def _fixed_engine(*values: int) -> Dnd5eEngine:
    rolls = iter(values)
    return Dnd5eEngine(roll_d20=lambda: next(rolls))


def _dnd5e_registry(*values: int) -> CommandRegistry:
    commands = CommandRegistry()
    systems = RuleSystemRegistry()
    systems.register(Dnd5eRuleSystem(engine=_fixed_engine(*values)))
    systems.register_commands(commands)
    return commands


def _group_event(text: str) -> dict:
    return {
        "self_id": "90001",
        "post_type": "message",
        "message_type": "group",
        "message_id": "30003",
        "group_id": "20002",
        "user_id": "10001",
        "sender": {"nickname": "冒险者"},
        "message": [{"type": "text", "data": {"text": text}}],
    }


@pytest.mark.parametrize(
    ("mode", "rolls", "selected", "total"),
    [
        (D20RollMode.NORMAL, (12,), 12, 17),
        (D20RollMode.ADVANTAGE, (7, 16), 16, 21),
        (D20RollMode.DISADVANTAGE, (7, 16), 7, 12),
    ],
)
def test_dnd5e_check_resolves_mode_and_modifier_in_python(
    mode: D20RollMode,
    rolls: tuple[int, ...],
    selected: int,
    total: int,
) -> None:
    result = _fixed_engine(*rolls).check(modifier=5, mode=mode)

    assert result.rolls == rolls
    assert result.selected_roll == selected
    assert result.total == total


@pytest.mark.parametrize(
    ("text", "rolls", "expected"),
    [
        (".dnd5e check", (12,), "🎲 DND 5e 普通检定：[12] = 12"),
        (".dnd5e check +5", (12,), "🎲 DND 5e 普通检定：[12] + 5 = 17"),
        (
            ".dnd5e check adv +5",
            (7, 16),
            "🎲 DND 5e 优势检定：[7, 16] → 16 + 5 = 21",
        ),
        (
            ".dnd5e check dis -1",
            (7, 16),
            "🎲 DND 5e 劣势检定：[7, 16] → 7 - 1 = 6",
        ),
    ],
)
def test_dnd5e_command_dispatches_explicit_2014_rules(
    text: str,
    rolls: tuple[int, ...],
    expected: str,
) -> None:
    result = _dnd5e_registry(*rolls).dispatch(text)

    assert result is not None
    assert result.content == expected


def test_dnd5e_does_not_claim_dnd5r_or_ambiguous_aliases() -> None:
    registry = _dnd5e_registry()

    assert registry.dispatch(".dnd check +5") is None
    assert registry.dispatch(".dnd5r check +5") is None


@pytest.mark.parametrize(
    "text",
    [
        ".dnd5e",
        ".dnd5e attack +5",
        ".dnd5e check advantage disadvantage +5",
        ".dnd5e check five",
    ],
)
def test_invalid_dnd5e_command_returns_usage_without_rolling(text: str) -> None:
    engine = Dnd5eEngine(roll_d20=lambda: pytest.fail("不应为无效命令掷骰"))
    commands = CommandRegistry()
    systems = RuleSystemRegistry()
    systems.register(Dnd5eRuleSystem(engine=engine))
    systems.register_commands(commands)

    result = commands.dispatch(text)

    assert result is not None
    assert result.content.startswith("DND 5e 命令格式：")


@pytest.mark.asyncio
async def test_dnd5e_command_bypasses_llm_in_onebot_route(tmp_path) -> None:
    repository = SQLiteConversationRepository(tmp_path / "memory.sqlite3")
    await repository.initialize()
    sender = AsyncMock()
    chat_core = SimpleNamespace(
        should_process_message=AsyncMock(),
        handle_chat_message=AsyncMock(),
    )
    event = _group_event(".dnd5e check adv +5")

    handled = await handle_persistent_onebot_chat_event(
        sender,
        event,
        chat_core,
        repository,
        _dnd5e_registry(7, 16),
    )

    assert handled is True
    sender.send_message.assert_awaited_once_with(
        event,
        "🎲 DND 5e 优势检定：[7, 16] → 16 + 5 = 21",
    )
    chat_core.should_process_message.assert_not_awaited()
    chat_core.handle_chat_message.assert_not_awaited()
