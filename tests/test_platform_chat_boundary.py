import ast
import inspect
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

import src.chat.services.chat_service as chat_service_module
import src.chat.services.prompt_service as prompt_service_module
from src.chat.platform import (
    ConversationContext,
    ConversationKind,
    IncomingMessage,
    ThreadContext,
)
from src.chat.services.chat_service import ChatService
from src.chat.services.prompt_service import PromptService


def _imported_roots(module) -> set[str]:
    syntax_tree = ast.parse(inspect.getsource(module))
    imported_roots = set()

    for node in ast.walk(syntax_tree):
        if isinstance(node, ast.Import):
            imported_roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_roots.add(node.module.split(".", 1)[0])

    return imported_roots


def test_chat_and_prompt_services_do_not_import_discord_sdk():
    assert "discord" not in _imported_roots(chat_service_module)
    assert "discord" not in _imported_roots(prompt_service_module)


def test_prompt_formats_thread_data_without_platform_object():
    conversation = ConversationContext(
        conversation_id="30003",
        kind=ConversationKind.THREAD,
        name="旧宅调查",
        space_id="40004",
        space_name="TRPG Group",
        thread=ThreadContext(
            owner_id="10001",
            owner_name="调查员",
            parent_id="50005",
            parent_name="跑团区",
            tags=("COC", "进行中"),
            starter_text="调查员收到了一封没有署名的信。",
        ),
    )

    result = PromptService._format_thread_first_post(conversation)

    assert result is not None
    assert "帖子标题: 旧宅调查" in result
    assert "发帖人: 调查员" in result
    assert "标签: COC, 进行中" in result
    assert "调查员收到了一封没有署名的信。" in result


@pytest.mark.asyncio
@pytest.mark.parametrize("cache_optimized", [False, True])
async def test_prompt_builds_both_paths_from_platform_thread_data(cache_optimized):
    conversation = ConversationContext(
        conversation_id="30003",
        kind=ConversationKind.THREAD,
        name="旧宅调查",
        thread=ThreadContext(
            owner_name="调查员",
            tags=("COC",),
            starter_text="首楼线索。",
        ),
    )
    service = PromptService()

    with patch.object(
        service,
        "_should_use_cache_optimized_build",
        return_value=cache_optimized,
    ):
        messages = await service.build_chat_prompt(
            user_name="调查员",
            message="检查门锁",
            replied_message=None,
            images=None,
            channel_context=None,
            world_book_entries=None,
            affection_status=None,
            guild_name="周末团",
            location_name="旧宅调查",
            conversation=conversation,
        )

    serialized = repr(messages)
    assert "<thread_first_post>" in serialized
    assert "帖子标题: 旧宅调查" in serialized
    assert "首楼线索。" in serialized


@pytest.mark.asyncio
async def test_chat_precheck_accepts_platform_neutral_group_message():
    incoming = IncomingMessage(
        platform="qq",
        message_id="90009",
        user_id="10001",
        user_name="调查员",
        text="骰 2d6+3",
        conversation=ConversationContext(
            conversation_id="20002",
            kind=ConversationKind.GROUP,
            name="周末团",
            space_id="20002",
            space_name="周末团",
        ),
    )
    request = SimpleNamespace(
        message=incoming,
        get_effective_chat_config=AsyncMock(
            return_value={"is_chat_enabled": True}
        ),
    )

    with (
        patch.object(
            chat_service_module.chat_settings_service,
            "is_chat_globally_enabled",
            new=AsyncMock(return_value=True),
        ),
        patch.object(
            chat_service_module.chat_settings_service,
            "is_user_on_cooldown",
            new=AsyncMock(return_value=False),
        ) as is_on_cooldown,
        patch.object(
            chat_service_module.chat_settings_service,
            "update_user_cooldown",
            new=AsyncMock(),
        ) as update_cooldown,
        patch.object(
            chat_service_module.chat_db_manager,
            "is_user_blacklisted",
            new=AsyncMock(return_value=False),
        ),
    ):
        result = await ChatService().should_process_message(request)

    assert result is True
    is_on_cooldown.assert_awaited_once_with(
        10001,
        20002,
        {"is_chat_enabled": True},
    )
    update_cooldown.assert_awaited_once_with(
        10001,
        20002,
        {"is_chat_enabled": True},
    )


@pytest.mark.asyncio
async def test_chat_generation_uses_platform_message_without_raw_discord_object():
    incoming = IncomingMessage(
        platform="qq",
        message_id="90009",
        user_id="10001",
        user_name="调查员",
        text="检查门锁",
        conversation=ConversationContext(
            conversation_id="20002",
            kind=ConversationKind.GROUP,
            name="周末团",
            space_id="20002",
            space_name="周末团",
        ),
    )
    request = SimpleNamespace(
        message=incoming,
        get_formatted_history=AsyncMock(return_value=[]),
        execute_tool_call=AsyncMock(),
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

    with (
        patch.object(
            chat_service_module.world_book_service,
            "get_profile_by_user_id",
            new=AsyncMock(return_value=None),
        ) as profile_lookup,
        patch.object(
            chat_service_module.affection_service,
            "get_affection_status",
            new=AsyncMock(return_value=None),
        ),
        patch.object(
            chat_service_module.persona_preference_service,
            "get_persona_style",
            new=AsyncMock(return_value="default"),
        ),
        patch.object(
            chat_service_module.affection_service,
            "increase_affection_on_message",
            new=AsyncMock(),
        ),
        patch.object(
            chat_service_module.coin_service,
            "grant_daily_message_reward",
            new=AsyncMock(return_value=False),
        ),
        patch.object(
            chat_service_module.chat_settings_service,
            "get_current_ai_model",
            new=AsyncMock(return_value="test-model"),
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
        ) as build_prompt,
        patch.object(
            chat_service_module.ai_service,
            "parse_model_id",
            return_value=("test-model", None),
        ),
        patch.object(
            chat_service_module.ai_service,
            "get_provider_for_model",
            return_value=SimpleNamespace(provider_type="openai"),
        ),
        patch.object(
            chat_service_module.ai_service,
            "_tool_service",
            new=SimpleNamespace(
                get_dynamic_tools_for_context=AsyncMock(return_value=[])
            ),
        ),
        patch.object(
            chat_service_module.ai_service,
            "generate_with_tools",
            new=AsyncMock(return_value=SimpleNamespace(content="门锁看起来很旧。")),
        ),
        patch(
            "src.chat.services.ai.config.models.get_generation_config",
            return_value=generation_params,
        ),
    ):
        result = await ChatService().handle_chat_message(request)

    assert result is not None
    assert result.content == "门锁看起来很旧。"
    request.get_formatted_history.assert_awaited_once_with()
    profile_lookup.assert_awaited_once_with("10001")
    prompt_kwargs = build_prompt.await_args.kwargs
    assert prompt_kwargs["user_name"] == "调查员"
    assert prompt_kwargs["message"] == "检查门锁"
    assert prompt_kwargs["conversation"] is incoming.conversation
