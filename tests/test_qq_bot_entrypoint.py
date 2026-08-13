from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.qq_bot import (
    DEFAULT_QQ_AI_MODEL,
    QQBotSettings,
    QQConfigurationError,
    create_qq_command_registry,
    create_qq_tool_registry,
    initialize_qq_chat_core,
    load_qq_settings,
    process_onebot_events,
)


def _valid_env() -> dict[str, str]:
    return {
        "ONEBOT_WS_URL": "ws://127.0.0.1:3001",
        "ONEBOT_ACCESS_TOKEN": "local-test-token",
        "DEEPSEEK_API_KEY": "local-test-key",
    }


def test_load_settings_uses_safe_deepseek_default() -> None:
    settings = load_qq_settings(_valid_env())

    assert settings.ai_model == DEFAULT_QQ_AI_MODEL
    assert settings.reconnect_seconds == 5.0


def test_non_deepseek_model_does_not_require_deepseek_key() -> None:
    environ = _valid_env()
    environ.pop("DEEPSEEK_API_KEY")
    environ["QQ_AI_MODEL"] = "openai_compatible:gpt-4o"

    settings = load_qq_settings(environ)

    assert settings.ai_model == "openai_compatible:gpt-4o"


def test_qq_runtime_registers_traditional_dice_command() -> None:
    registry = create_qq_command_registry()

    assert registry.dispatch("ordinary chat") is None
    assert registry.dispatch(".r") is not None
    assert registry.dispatch(".dnd5e check") is not None
    assert registry.dispatch(".dnd5r check") is None


def test_qq_runtime_registers_dice_and_dnd5e_llm_tools() -> None:
    registry = create_qq_tool_registry()

    assert [item.name for item in registry.declarations()] == [
        "roll_dice",
        "dnd5e_check",
    ]


@pytest.mark.parametrize(
    ("missing_key", "expected_name"),
    [
        ("ONEBOT_WS_URL", "ONEBOT_WS_URL"),
        ("ONEBOT_ACCESS_TOKEN", "ONEBOT_ACCESS_TOKEN"),
        ("DEEPSEEK_API_KEY", "DEEPSEEK_API_KEY"),
    ],
)
def test_load_settings_explains_missing_configuration(
    missing_key: str,
    expected_name: str,
) -> None:
    environ = _valid_env()
    environ.pop(missing_key)

    with pytest.raises(QQConfigurationError, match=expected_name):
        load_qq_settings(environ)


@pytest.mark.parametrize("url", ["http://127.0.0.1:3001", "not-a-url"])
def test_load_settings_rejects_non_websocket_url(url: str) -> None:
    environ = _valid_env()
    environ["ONEBOT_WS_URL"] = url

    with pytest.raises(QQConfigurationError, match="WebSocket"):
        load_qq_settings(environ)


@pytest.mark.asyncio
async def test_one_failed_event_does_not_stop_later_messages() -> None:
    events = [{"message_id": "1"}, {"message_id": "2"}]

    class FakeClient:
        async def events(self):
            for event in events:
                yield event

    handler = AsyncMock(side_effect=[RuntimeError("bad message"), True])
    chat_core = SimpleNamespace()
    client = FakeClient()

    await process_onebot_events(client, chat_core, event_handler=handler)

    assert handler.await_count == 2
    assert handler.await_args_list[1].args == (client, events[1], chat_core)


@pytest.mark.asyncio
async def test_qq_runtime_uses_environment_ai_when_postgres_is_absent(
    monkeypatch,
) -> None:
    from src.chat.services.ai.service import ai_service
    from src.chat.services.chat_service import chat_service
    from src.chat.utils.database import chat_db_manager
    from src.chat.features.world_book.database.world_book_db_manager import (
        world_book_db_manager,
    )
    import src.database.database as database_module

    monkeypatch.setattr(chat_db_manager, "init_async", AsyncMock())
    monkeypatch.setattr(world_book_db_manager, "init_async", AsyncMock())
    monkeypatch.setattr(
        database_module,
        "optional_chat_database_is_ready",
        AsyncMock(return_value=False),
    )
    monkeypatch.setattr(ai_service, "set_tools", lambda *_args: None)
    monkeypatch.setattr(chat_service, "_optional_postgres_enabled", True)
    initialize_without_database = AsyncMock()
    monkeypatch.setattr(
        ai_service,
        "initialize_without_database",
        initialize_without_database,
    )
    initialize_with_database = AsyncMock()
    monkeypatch.setattr(ai_service, "initialize", initialize_with_database)
    monkeypatch.setattr(
        ai_service,
        "parse_model_id",
        lambda _model: ("deepseek-chat", "deepseek"),
    )
    monkeypatch.setattr(ai_service, "get_provider_for_model", lambda *_args: object())
    monkeypatch.setattr(chat_db_manager, "set_global_setting", AsyncMock())

    core = await initialize_qq_chat_core(
        QQBotSettings("ws://127.0.0.1:3001", "token")
    )

    assert core is chat_service
    assert chat_service._optional_postgres_enabled is False
    initialize_without_database.assert_awaited_once_with()
    initialize_with_database.assert_not_awaited()
