from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.qq_bot import (
    DEFAULT_QQ_AI_MODEL,
    QQConfigurationError,
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
