from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

import src.chat.services.chat_service as chat_service_module
from src.chat.dice import DiceEngine, register_dice_tools
from src.chat.dice.tool import message_requests_dice
from src.chat.platform import ConversationContext, ConversationKind, IncomingMessage
from src.chat.services.chat_service import ChatService
from src.chat.tools import PortableToolService, ToolRegistry


def _fixed_engine(*values: int) -> DiceEngine:
    rolls = iter(values)
    return DiceEngine(roll_die=lambda _sides: next(rolls))


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("这是目前最后一关了", False),
        ("10-1吧", False),
        ("我推是斯佩", False),
        ("这个骰娘很可爱", False),
        ("我们刚才聊了骰子机制", False),
        ("1d100", True),
        ("帮我骰 2d6+3", True),
        ("做一次侦查检定", True),
        ("随机决定一下谁先走", True),
    ],
)
def test_dice_intent_requires_current_message_request(
    message: str, expected: bool
) -> None:
    assert message_requests_dice(message) is expected


@pytest.mark.asyncio
async def test_roll_dice_is_hidden_and_rejected_for_ordinary_narration() -> None:
    registry = ToolRegistry()
    register_dice_tools(registry, _fixed_engine(33))
    service = PortableToolService(registry)

    tools = await service.get_dynamic_tools_for_context(
        provider_type="deepseek", user_text="这是目前最后一关了"
    )
    payload = await service.execute_tool_call(
        {"name": "roll_dice", "arguments": {"expression": "1d100"}},
        user_text="这是目前最后一关了",
    )

    assert tools == []
    assert "error" in payload
    assert "authoritative_output" not in payload


@pytest.mark.asyncio
async def test_roll_dice_tool_returns_structured_authoritative_result() -> None:
    registry = ToolRegistry()
    register_dice_tools(registry, _fixed_engine(4, 2))
    service = PortableToolService(registry)

    tools = await service.get_dynamic_tools_for_context(provider_type="deepseek")
    payload = await service.execute_tool_call(
        {"name": "roll_dice", "arguments": {"expression": "2d6+3"}},
        user_id="10001",
        platform="qq",
    )

    assert tools[0]["function"]["name"] == "roll_dice"
    assert tools[0]["function"]["parameters"]["required"] == ["expression"]
    assert payload == {
        "ok": True,
        "tool": "roll_dice",
        "result": {
            "notation": "2d6+3",
            "rolls": [4, 2],
            "modifier": 3,
            "total": 9,
        },
        "authoritative_output": "🎲 2d6+3 = [4, 2] + 3 = 9",
    }


@pytest.mark.asyncio
async def test_invalid_llm_dice_arguments_return_error_without_random_result() -> None:
    registry = ToolRegistry()
    register_dice_tools(registry)
    service = PortableToolService(registry)

    payload = await service.execute_tool_call(
        {"name": "roll_dice", "arguments": {"expression": "1000d6"}}
    )

    assert "error" in payload
    assert "authoritative_output" not in payload


@pytest.mark.asyncio
@pytest.mark.parametrize("narration_fails", [False, True])
async def test_chat_keeps_python_result_even_if_llm_narration_fails(
    narration_fails: bool,
) -> None:
    incoming = IncomingMessage(
        platform="qq",
        message_id="30003",
        user_id="10001",
        user_name="调查员",
        text="帮我骰 2d6+3",
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
                "result": {
                    "notation": "2d6+3",
                    "rolls": [4, 2],
                    "modifier": 3,
                    "total": 9,
                },
                "authoritative_output": "🎲 2d6+3 = [4, 2] + 3 = 9",
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
            {"name": "roll_dice", "arguments": {"expression": "2d6+3"}}
        )
        if narration_fails:
            raise RuntimeError("narration unavailable")
        return SimpleNamespace(
            content="🎲 2d6+3 = 9\n骰子落定，这次结果是九点。"
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
        patch.object(
            chat_service_module.ai_service,
            "_tool_service",
            new=tool_service,
        ),
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
            "🎲 2d6+3 = [4, 2] + 3 = 9"
            "\n\n（骰子结果已生成，但 AI 表述暂时失败。）"
        )
    else:
        assert result.content == (
            "🎲 2d6+3 = [4, 2] + 3 = 9\n\n骰子落定，这次结果是九点。"
        )
    assert result.authoritative_outputs == ["🎲 2d6+3 = [4, 2] + 3 = 9"]
    assert result.tools_called == ["roll_dice"]
    assert request.execute_tool_call.await_args.kwargs["user_text"] == "帮我骰 2d6+3"
