from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.chat.actions import ActionContext, ActionResult
from src.chat.commands import CommandRegistry
from src.chat.memory import SQLiteConversationRepository
from src.chat.platform.onebot.persistent_chat import (
    handle_persistent_onebot_chat_event,
)
from src.chat.rules import RuleSystemRegistry
from src.chat.rules.dnd5e import (
    D20RollMode,
    Dnd5eCheckAction,
    Dnd5eCheckError,
    Dnd5eCheckRequest,
    Dnd5eEngine,
    Dnd5eRuleSystem,
    ability_modifier,
    resolve_check_modifier,
)


def _fixed_engine(*values: int) -> Dnd5eEngine:
    rolls = iter(values)
    return Dnd5eEngine(roll_d20=lambda: next(rolls))


def _dnd5e_registry(*values: int) -> CommandRegistry:
    commands = CommandRegistry()
    systems = RuleSystemRegistry()
    systems.register(Dnd5eRuleSystem(engine=_fixed_engine(*values)))
    systems.register_commands(commands)
    return commands


async def _execute_request(
    engine: Dnd5eEngine,
    request: Dnd5eCheckRequest,
) -> ActionResult:
    action = Dnd5eCheckAction(engine)
    return await action.execute(
        request,
        ActionContext(user_id="10001", user_name="冒险者", platform="qq"),
    )


def _no_roll_engine() -> Dnd5eEngine:
    return Dnd5eEngine(roll_d20=lambda: pytest.fail("不应为无效请求掷骰"))


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
@pytest.mark.asyncio
async def test_dnd5e_command_dispatches_explicit_2014_rules(
    text: str,
    rolls: tuple[int, ...],
    expected: str,
) -> None:
    result = await _dnd5e_registry(*rolls).dispatch(text)

    assert result is not None
    assert result.content == expected


@pytest.mark.asyncio
async def test_dnd5e_does_not_claim_dnd5r_or_ambiguous_aliases() -> None:
    registry = _dnd5e_registry()

    assert await registry.dispatch(".dnd check +5") is None
    assert await registry.dispatch(".dnd5r check +5") is None


@pytest.mark.parametrize(
    "text",
    [
        ".dnd5e",
        ".dnd5e attack +5",
        ".dnd5e check advantage disadvantage +5",
        ".dnd5e check five",
    ],
)
@pytest.mark.asyncio
async def test_invalid_dnd5e_command_returns_usage_without_rolling(
    text: str,
) -> None:
    engine = Dnd5eEngine(roll_d20=lambda: pytest.fail("不应为无效命令掷骰"))
    commands = CommandRegistry()
    systems = RuleSystemRegistry()
    systems.register(Dnd5eRuleSystem(engine=engine))
    systems.register_commands(commands)

    result = await commands.dispatch(text)

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


@pytest.mark.parametrize(
    ("score", "expected"),
    [
        (18, 4),
        (14, 2),
        (13, 1),
        (10, 0),
        (9, -1),
        (7, -2),
    ],
)
def test_ability_modifier_computes_floor_half_minus_five(
    score: int,
    expected: int,
) -> None:
    assert ability_modifier(score) == expected


@pytest.mark.asyncio
async def test_structured_check_computes_modifier_in_python() -> None:
    result = await _execute_request(
        _fixed_engine(12),
        Dnd5eCheckRequest(
            mode=D20RollMode.NORMAL,
            ability_score=18,
            proficiency_bonus=2,
        ),
    )

    assert result.data == {
        "ruleset": "dnd5e",
        "mode": "normal",
        "rolls": [12],
        "selected_roll": 12,
        "modifier": 6,
        "total": 18,
        "modifier_breakdown": {
            "ability_score": 18,
            "ability_modifier": 4,
            "proficiency_bonus": 2,
            "misc_modifier": 0,
        },
    }
    assert result.authoritative_output == (
        "🎲 DND 5e 普通检定：[12] + 6 = 18"
    )


@pytest.mark.asyncio
async def test_structured_advantage_check_takes_highest_roll() -> None:
    result = await _execute_request(
        _fixed_engine(13, 20),
        Dnd5eCheckRequest(
            mode=D20RollMode.ADVANTAGE,
            ability_score=18,
            proficiency_bonus=2,
        ),
    )

    assert result.data["rolls"] == [13, 20]
    assert result.data["selected_roll"] == 20
    assert result.data["modifier"] == 6
    assert result.data["total"] == 26
    assert result.data["modifier_breakdown"]["ability_modifier"] == 4
    assert result.authoritative_output == (
        "🎲 DND 5e 优势检定：[13, 20] → 20 + 6 = 26"
    )


@pytest.mark.asyncio
async def test_structured_check_includes_misc_modifier() -> None:
    modifier, breakdown = resolve_check_modifier(
        Dnd5eCheckRequest(
            ability_score=14,
            proficiency_bonus=2,
            misc_modifier=1,
        )
    )

    assert modifier == 5
    assert breakdown == {
        "ability_score": 14,
        "ability_modifier": 2,
        "proficiency_bonus": 2,
        "misc_modifier": 1,
    }


@pytest.mark.asyncio
async def test_direct_modifier_keeps_legacy_payload_and_output() -> None:
    result = await _execute_request(
        _fixed_engine(12),
        Dnd5eCheckRequest(mode=D20RollMode.NORMAL, modifier=5),
    )

    assert result.data == {
        "ruleset": "dnd5e",
        "mode": "normal",
        "rolls": [12],
        "selected_roll": 12,
        "modifier": 5,
        "total": 17,
    }
    assert "modifier_breakdown" not in result.data
    assert result.authoritative_output == (
        "🎲 DND 5e 普通检定：[12] + 5 = 17"
    )


@pytest.mark.asyncio
async def test_empty_request_defaults_to_zero_modifier() -> None:
    result = await _execute_request(
        _fixed_engine(12),
        Dnd5eCheckRequest(mode=D20RollMode.NORMAL),
    )

    assert result.data["modifier"] == 0
    assert result.data["total"] == 12
    assert "modifier_breakdown" not in result.data


@pytest.mark.parametrize(
    "check_request",
    [
        Dnd5eCheckRequest(modifier=6, ability_score=18),
        Dnd5eCheckRequest(modifier=6, proficiency_bonus=2),
        Dnd5eCheckRequest(modifier=6, misc_modifier=1),
    ],
)
@pytest.mark.asyncio
async def test_mixing_direct_modifier_with_components_is_rejected(
    check_request: Dnd5eCheckRequest,
) -> None:
    with pytest.raises(Dnd5eCheckError, match="不能同时提供"):
        resolve_check_modifier(check_request)


@pytest.mark.parametrize(
    "ability_score",
    [0, 31, True, False, 2.5, "18"],
)
def test_invalid_ability_score_is_rejected(ability_score: object) -> None:
    with pytest.raises(Dnd5eCheckError):
        resolve_check_modifier(
            Dnd5eCheckRequest(ability_score=ability_score)  # type: ignore[arg-type]
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("proficiency_bonus", True),
        ("proficiency_bonus", False),
        ("proficiency_bonus", 1.5),
        ("proficiency_bonus", "2"),
        ("misc_modifier", True),
        ("misc_modifier", False),
        ("misc_modifier", 1.5),
        ("misc_modifier", "1"),
    ],
)
def test_invalid_component_types_are_rejected(
    field: str,
    value: object,
) -> None:
    with pytest.raises(Dnd5eCheckError, match="必须是整数"):
        resolve_check_modifier(
            Dnd5eCheckRequest(**{field: value})  # type: ignore[arg-type]
        )


@pytest.mark.asyncio
async def test_invalid_requests_never_produce_a_random_result() -> None:
    engine = _no_roll_engine()
    with pytest.raises(Dnd5eCheckError):
        await _execute_request(
            engine,
            Dnd5eCheckRequest(modifier=6, ability_score=18),
        )