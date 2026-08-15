from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

import src.chat.services.chat_service as chat_service_module
from src.chat.actions import ActionContext, ActionResult
from src.chat.commands import CommandRegistry
from src.chat.platform import ConversationContext, ConversationKind, IncomingMessage
from src.chat.rules.dnd5e import (
    D20RollMode,
    Dnd5eCheckRequest,
    Dnd5eEngine,
    register_dnd5e_commands,
    register_dnd5e_tools,
)
from src.chat.rules.dnd5e.tool import message_requests_dnd5e_check
from src.chat.services.chat_service import ChatService
from src.chat.tools import PortableToolService, ToolRegistry


def _fixed_engine(*values: int) -> Dnd5eEngine:
    rolls = iter(values)
    return Dnd5eEngine(roll_d20=lambda: next(rolls))


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("这是目前最后一关了", False),
        ("看看我的角色卡列表", False),
        ("生成一个COC7调查员", False),
        ("给我做一次COC7 SAN check", False),
        ("DND5e优势检定是怎么算的", False),
        ("介绍一下DND5e豁免规则", False),
        ("帮我做一次DND5e优势检定", True),
        ("D&D 5e 来一次攻击检定", True),
        ("我在玩DND5e，请给我进行一次优势攻击检定", True),
        ("DND5e +5优势检定", True),
        ("骰个d6", False),
        ("来个2d6+3", False),
        ("帮我做一次DND5e优势检定，加值5", True),
        ("DND5e里帮我骰个d20", False),
        ("DND5e里帮我骰1d20", False),
        ("DND5e d20检定", True),
        ("COC7里先帮我骰个1d100", False),
    ],
)
def test_dnd5e_tool_requires_explicit_current_message_request(
    message: str,
    expected: bool,
) -> None:
    assert message_requests_dnd5e_check(message) is expected


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("message", "expected_roll_dice", "expected_dnd5e_check"),
    [
        ("这是目前最后一关了", False, False),
        ("骰个d6", True, False),
        ("来个2d6+3", True, False),
        ("帮我做一次DND5e优势检定，加值5", False, True),
        ("D&D 5e 来一次攻击检定", False, True),
        ("DND5e里帮我骰个d20", True, False),
        ("DND5e里帮我骰1d20", True, False),
        ("DND5e d20检定", False, True),
        ("生成一个COC7调查员", False, False),
        ("给我做一次COC7 SAN check", False, False),
        ("COC7里先帮我骰个1d100", True, False),
    ],
)
async def test_roll_dice_and_dnd5e_check_are_mutually_exclusive(
    message: str,
    expected_roll_dice: bool,
    expected_dnd5e_check: bool,
) -> None:
    from src.chat.dice import register_dice_tools

    registry = ToolRegistry()
    register_dice_tools(registry)
    register_dnd5e_tools(registry)
    service = PortableToolService(registry)

    tools = await service.get_dynamic_tools_for_context(
        provider_type="deepseek", user_text=message
    )
    available_names = {tool["function"]["name"] for tool in tools}

    assert ("roll_dice" in available_names) is expected_roll_dice
    assert ("dnd5e_check" in available_names) is expected_dnd5e_check


@pytest.mark.asyncio
async def test_dnd5e_tool_is_hidden_for_coc_request() -> None:
    registry = ToolRegistry()
    register_dnd5e_tools(registry, _fixed_engine(12))
    service = PortableToolService(registry)

    tools = await service.get_dynamic_tools_for_context(
        provider_type="deepseek",
        user_text="生成一个COC7调查员",
    )
    payload = await service.execute_tool_call(
        {
            "name": "dnd5e_check",
            "arguments": {"mode": "normal", "modifier": 0},
        },
        user_text="生成一个COC7调查员",
    )

    assert tools == []
    assert "error" in payload
    assert "authoritative_output" not in payload


@pytest.mark.asyncio
async def test_dnd5e_tool_is_available_for_explicit_dnd5e_check() -> None:
    registry = ToolRegistry()
    register_dnd5e_tools(registry, _fixed_engine(16, 7))
    service = PortableToolService(registry)

    tools = await service.get_dynamic_tools_for_context(
        provider_type="deepseek",
        user_text="帮我做一次DND5e优势检定，加值5",
    )

    assert len(tools) == 1
    assert tools[0]["function"]["name"] == "dnd5e_check"


@pytest.mark.asyncio
async def test_command_and_tool_share_one_dnd5e_action() -> None:
    calls: list[tuple[Dnd5eCheckRequest, ActionContext]] = []

    class RecordingAction:
        async def execute(self, request, context):
            calls.append((request, context))
            return ActionResult(
                data={
                    "ruleset": "dnd5e",
                    "mode": request.mode.value,
                    "rolls": [7, 16],
                    "selected_roll": 16,
                    "modifier": request.modifier,
                    "total": 21,
                },
                authoritative_output=(
                    "🎲 DND 5e 优势检定：[7, 16] → 16 + 5 = 21"
                ),
            )

    action = RecordingAction()
    commands = CommandRegistry()
    register_dnd5e_commands(commands, action=action)
    tools = ToolRegistry()
    register_dnd5e_tools(tools, action=action)
    tool_service = PortableToolService(tools)
    command_context = ActionContext(
        user_id="10001",
        user_name="冒险者",
        platform="qq",
    )

    command_result = await commands.dispatch(
        ".dnd5e check adv +5",
        command_context,
    )
    tool_result = await tool_service.execute_tool_call(
        {
            "name": "dnd5e_check",
            "arguments": {"mode": "advantage", "modifier": 5},
        },
        user_id="10001",
        user_name="冒险者",
        platform="qq",
    )

    assert command_result is not None
    assert command_result.content == tool_result["authoritative_output"]
    assert calls == [
        (
            Dnd5eCheckRequest(mode=D20RollMode.ADVANTAGE, modifier=5),
            command_context,
        ),
        (
            Dnd5eCheckRequest(mode=D20RollMode.ADVANTAGE, modifier=5),
            command_context,
        ),
    ]


@pytest.mark.asyncio
async def test_dnd5e_tool_returns_structured_authoritative_result() -> None:
    registry = ToolRegistry()
    register_dnd5e_tools(registry, _fixed_engine(7, 16))
    service = PortableToolService(registry)

    tools = await service.get_dynamic_tools_for_context(provider_type="deepseek")
    payload = await service.execute_tool_call(
        {
            "name": "dnd5e_check",
            "arguments": {"mode": "advantage", "modifier": 5},
        },
        user_id="10001",
        platform="qq",
    )

    function = tools[0]["function"]
    assert function["name"] == "dnd5e_check"
    assert function["parameters"]["properties"]["mode"]["enum"] == [
        "normal",
        "advantage",
        "disadvantage",
    ]
    assert payload == {
        "ok": True,
        "tool": "dnd5e_check",
        "result": {
            "ruleset": "dnd5e",
            "mode": "advantage",
            "rolls": [7, 16],
            "selected_roll": 16,
            "modifier": 5,
            "total": 21,
        },
        "authoritative_output": "🎲 DND 5e 优势检定：[7, 16] → 16 + 5 = 21",
    }


@pytest.mark.asyncio
async def test_dnd5e_tool_defaults_to_normal_check_with_zero_modifier() -> None:
    registry = ToolRegistry()
    register_dnd5e_tools(registry, _fixed_engine(12))
    service = PortableToolService(registry)

    payload = await service.execute_tool_call(
        {"name": "dnd5e_check", "arguments": {}}
    )

    assert payload["result"] == {
        "ruleset": "dnd5e",
        "mode": "normal",
        "rolls": [12],
        "selected_roll": 12,
        "modifier": 0,
        "total": 12,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "arguments",
    [
        {"mode": "adv", "modifier": 5},
        {"mode": "normal", "modifier": 2.5},
        {"mode": "normal", "modifier": True},
        {"mode": "normal", "modifier": 1_000_001},
        {"mode": "normal", "modifier": 0, "dc": 15},
    ],
)
async def test_invalid_dnd5e_tool_arguments_do_not_return_random_result(
    arguments: dict,
) -> None:
    registry = ToolRegistry()
    register_dnd5e_tools(registry)
    service = PortableToolService(registry)

    payload = await service.execute_tool_call(
        {"name": "dnd5e_check", "arguments": arguments}
    )

    assert "error" in payload
    assert "authoritative_output" not in payload


@pytest.mark.asyncio
@pytest.mark.parametrize("narration_fails", [False, True])
async def test_chat_keeps_dnd5e_result_when_llm_narration_fails_or_repeats(
    narration_fails: bool,
) -> None:
    authoritative_output = "🎲 DND 5e 优势检定：[7, 16] → 16 + 5 = 21"
    incoming = IncomingMessage(
        platform="qq",
        message_id="30003",
        user_id="10001",
        user_name="冒险者",
        text="帮我做一次 DND 5e 优势检定，加值 5",
        conversation=ConversationContext(
            conversation_id="20002",
            kind=ConversationKind.GROUP,
            name="周末团",
        ),
    )
    request = SimpleNamespace(
        message=incoming,
        get_formatted_history=AsyncMock(return_value=[]),
        execute_tool_call=AsyncMock(
            return_value={
                "ok": True,
                "tool": "dnd5e_check",
                "result": {
                    "ruleset": "dnd5e",
                    "mode": "advantage",
                    "rolls": [7, 16],
                    "selected_roll": 16,
                    "modifier": 5,
                    "total": 21,
                },
                "authoritative_output": authoritative_output,
            }
        ),
    )
    generation_params = SimpleNamespace(
        temperature=0.7,
        top_p=0.9,
        top_k=40,
        max_output_tokens=1024,
        presence_penalty=0.0,
        frequency_penalty=0.0,
        thinking_budget_tokens=None,
    )

    async def generate_with_one_tool(*, tool_executor, **_kwargs):
        await tool_executor(
            {
                "name": "dnd5e_check",
                "arguments": {"mode": "advantage", "modifier": 5},
            }
        )
        if narration_fails:
            raise RuntimeError("narration unavailable")
        return SimpleNamespace(
            content=f"{authoritative_output}\n两枚骰子中取高，最终是二十一点。"
        )

    tool_service = SimpleNamespace(
        get_dynamic_tools_for_context=AsyncMock(return_value=[{"type": "function"}])
    )
    with (
        patch.object(
            chat_service_module.chat_settings_service,
            "get_current_ai_model",
            new=AsyncMock(return_value="deepseek:deepseek-chat"),
        ),
        patch.object(
            chat_service_module.chat_settings_service,
            "is_two_stage_enabled",
            new=AsyncMock(return_value=False),
        ),
        patch.object(
            chat_service_module.chat_settings_service,
            "increment_model_usage",
            new=AsyncMock(),
        ),
        patch.object(
            chat_service_module.prompt_service,
            "build_chat_prompt",
            new=AsyncMock(return_value=[]),
        ),
        patch.object(
            chat_service_module.ai_service,
            "parse_model_id",
            return_value=("deepseek-chat", "deepseek"),
        ),
        patch.object(
            chat_service_module.ai_service,
            "get_provider_for_model",
            return_value=SimpleNamespace(provider_type="deepseek"),
        ),
        patch.object(chat_service_module.ai_service, "_tool_service", new=tool_service),
        patch.object(
            chat_service_module.ai_service,
            "generate_with_tools",
            new=AsyncMock(side_effect=generate_with_one_tool),
        ),
        patch(
            "src.chat.services.ai.config.models.get_generation_config",
            return_value=generation_params,
        ),
    ):
        service = ChatService()
        service.set_optional_postgres_enabled(False)
        result = await service.handle_chat_message(request)

    assert result is not None
    if narration_fails:
        assert result.content == (
            f"{authoritative_output}\n\n（骰子结果已生成，但 AI 表述暂时失败。）"
        )
    else:
        assert result.content == (
            f"{authoritative_output}\n\n两枚骰子中取高，最终是二十一点。"
        )
    assert result.authoritative_outputs == [authoritative_output]
    assert result.tools_called == ["dnd5e_check"]


@pytest.mark.asyncio
async def test_dnd5e_tool_schema_exposes_structured_modifier_fields() -> None:
    registry = ToolRegistry()
    register_dnd5e_tools(registry, _fixed_engine(12))
    service = PortableToolService(registry)

    tools = await service.get_dynamic_tools_for_context(provider_type="deepseek")

    function = tools[0]["function"]
    properties = function["parameters"]["properties"]
    assert function["name"] == "dnd5e_check"
    assert set(properties) == {
        "mode",
        "modifier",
        "ability_score",
        "proficiency_bonus",
        "misc_modifier",
    }
    assert properties["modifier"]["type"] == "integer"
    assert properties["ability_score"]["type"] == "integer"
    assert properties["proficiency_bonus"]["type"] == "integer"
    assert properties["misc_modifier"]["type"] == "integer"
    assert function["parameters"]["additionalProperties"] is False
    assert "ability_score" in function["description"]
    assert "proficiency_bonus" in function["description"]
    assert "不得同时提供" in function["description"]

    definition = registry.get("dnd5e_check")
    assert definition is not None
    raw_parameters = definition.parameters
    assert raw_parameters["properties"]["ability_score"]["minimum"] == 1
    assert raw_parameters["properties"]["ability_score"]["maximum"] == 30


@pytest.mark.asyncio
async def test_dnd5e_tool_handles_realistic_structured_attack_check() -> None:
    registry = ToolRegistry()
    register_dnd5e_tools(registry, _fixed_engine(13, 20))
    service = PortableToolService(registry)

    payload = await service.execute_tool_call(
        {
            "name": "dnd5e_check",
            "arguments": {
                "mode": "advantage",
                "ability_score": 18,
                "proficiency_bonus": 2,
            },
        },
        user_id="10001",
        platform="qq",
    )

    assert payload == {
        "ok": True,
        "tool": "dnd5e_check",
        "result": {
            "ruleset": "dnd5e",
            "mode": "advantage",
            "rolls": [13, 20],
            "selected_roll": 20,
            "modifier": 6,
            "total": 26,
            "modifier_breakdown": {
                "ability_score": 18,
                "ability_modifier": 4,
                "proficiency_bonus": 2,
                "misc_modifier": 0,
            },
        },
        "authoritative_output": "🎲 DND 5e 优势检定：[13, 20] → 20 + 6 = 26",
    }
