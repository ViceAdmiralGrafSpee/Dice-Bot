"""Production entry point for the QQ / NapCat / OneBot chat bot.

Run from the repository root with::

    python -m src.qq_bot

This entry point deliberately loads only the shared chat flow. Discord cogs and
platform-specific tool functions remain available to the Discord entry point,
but are not started here.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
import logging
import os
from typing import Any, Protocol
from urllib.parse import urlparse

from dotenv import load_dotenv

from src.chat.platform.onebot.chat_gateway import (
    ChatCore,
    handle_onebot_chat_event,
)
from src.chat.memory import SQLiteConversationRepository
from src.chat.platform.onebot.persistent_chat import (
    handle_persistent_onebot_chat_event,
)
from src.chat.platform.onebot.transport import OneBotWebSocketClient
from src.chat.tools import PortableToolService, ToolRegistry


log = logging.getLogger(__name__)
DEFAULT_QQ_AI_MODEL = "deepseek:deepseek-chat"


class QQConfigurationError(RuntimeError):
    """Raised when the QQ process cannot start safely."""


@dataclass(frozen=True, slots=True)
class QQBotSettings:
    ws_url: str
    access_token: str
    ai_model: str = DEFAULT_QQ_AI_MODEL
    reconnect_seconds: float = 5.0


class OneBotClient(Protocol):
    async def __aenter__(self) -> "OneBotClient": ...

    async def __aexit__(self, *_args: Any) -> None: ...

    def events(self) -> Any: ...

    async def send_message(self, event: Mapping[str, Any], text: str) -> None: ...


EventHandler = Callable[[OneBotClient, Mapping[str, Any], ChatCore], Awaitable[bool]]


def load_qq_settings(
    environ: Mapping[str, str] | None = None,
) -> QQBotSettings:
    """Read and validate QQ settings without exposing secret values."""

    values = os.environ if environ is None else environ
    ws_url = values.get("ONEBOT_WS_URL", "").strip()
    access_token = values.get("ONEBOT_ACCESS_TOKEN", "").strip()
    ai_model = values.get("QQ_AI_MODEL", DEFAULT_QQ_AI_MODEL).strip()

    missing = []
    if not ws_url:
        missing.append("ONEBOT_WS_URL")
    if not access_token:
        missing.append("ONEBOT_ACCESS_TOKEN")
    if not ai_model:
        missing.append("QQ_AI_MODEL")
    if missing:
        raise QQConfigurationError(
            "缺少启动配置：" + "、".join(missing) + "。请填写本机 .env 文件。"
        )

    parsed_url = urlparse(ws_url)
    if parsed_url.scheme not in {"ws", "wss"} or not parsed_url.hostname:
        raise QQConfigurationError(
            "ONEBOT_WS_URL 不是有效的 WebSocket 地址，应类似 ws://127.0.0.1:3001。"
        )

    if ai_model.startswith("deepseek:") or ai_model.startswith("deepseek-"):
        if not values.get("DEEPSEEK_API_KEY", "").strip():
            raise QQConfigurationError(
                "当前选择了 DeepSeek，但缺少 DEEPSEEK_API_KEY。请只把 Key 填进本机 .env，不要提交到 Git。"
            )

    reconnect_text = values.get("QQ_RECONNECT_SECONDS", "5").strip()
    try:
        reconnect_seconds = float(reconnect_text)
    except ValueError as error:
        raise QQConfigurationError("QQ_RECONNECT_SECONDS 必须是数字。") from error
    if reconnect_seconds <= 0:
        raise QQConfigurationError("QQ_RECONNECT_SECONDS 必须大于 0。")

    return QQBotSettings(
        ws_url=ws_url,
        access_token=access_token,
        ai_model=ai_model,
        reconnect_seconds=reconnect_seconds,
    )


async def initialize_qq_chat_core(settings: QQBotSettings) -> ChatCore:
    """Initialize the existing platform-neutral chat flow for QQ."""

    # Keep these imports after configuration validation. A missing Key should
    # produce a clear error without starting database or AI components.
    from src.chat.features.world_book.database.world_book_db_manager import (
        world_book_db_manager,
    )
    from src.chat.services.ai.service import ai_service
    from src.chat.services.chat_service import chat_service
    from src.chat.utils.database import chat_db_manager
    from src.database.database import optional_chat_database_is_ready
    from src.chat.dice import register_dice_tools

    await chat_db_manager.init_async()
    await world_book_db_manager.init_async()

    tool_registry = ToolRegistry()
    register_dice_tools(tool_registry)
    tool_service = PortableToolService(tool_registry)
    declarations = tool_registry.declarations()
    ai_service.set_tools(
        declarations,
        {declaration.name: declaration.function for declaration in declarations},
        tool_service,
    )

    postgres_ready = await optional_chat_database_is_ready()
    chat_service.set_optional_postgres_enabled(postgres_ready)
    if postgres_ready:
        await ai_service.initialize()
    else:
        await ai_service.initialize_without_database()

    model_name, provider_name = ai_service.parse_model_id(settings.ai_model)
    if ai_service.get_provider_for_model(model_name, provider_name) is None:
        raise QQConfigurationError(
            f"QQ_AI_MODEL={settings.ai_model} 当前不可用，请检查对应的 AI Provider 配置。"
        )

    # The original Discord UI stores its model selection in SQLite. QQ has no
    # such UI yet, so the process configuration is the source of truth.
    await chat_db_manager.set_global_setting("ai_model", settings.ai_model)
    log.info(
        "QQ 聊天核心已就绪，当前模型：%s（已加载工具：roll_dice）",
        settings.ai_model,
    )
    return chat_service


async def process_onebot_events(
    client: OneBotClient,
    chat_core: ChatCore,
    *,
    event_handler: EventHandler = handle_onebot_chat_event,
) -> None:
    """Process events without letting one bad message disconnect the bot."""

    async for event in client.events():
        try:
            await event_handler(client, event, chat_core)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("处理一条 QQ 消息失败；连接会继续保持，请查看上方错误。")


async def run_qq_bot(settings: QQBotSettings) -> None:
    """Connect the shared chat core to NapCat and keep reconnecting."""

    chat_core = await initialize_qq_chat_core(settings)
    conversation_repository = SQLiteConversationRepository()
    await conversation_repository.initialize()

    async def persistent_event_handler(client, event, core) -> bool:
        return await handle_persistent_onebot_chat_event(
            client,
            event,
            core,
            conversation_repository,
        )

    try:
        while True:
            client = OneBotWebSocketClient(settings.ws_url, settings.access_token)
            try:
                log.info("正在连接 NapCat：%s", settings.ws_url)
                async with client:
                    log.info("QQ 骰娘已上线；私聊或在群里 @机器人即可触发 AI 回复。")
                    await process_onebot_events(
                        client,
                        chat_core,
                        event_handler=persistent_event_handler,
                    )
            except asyncio.CancelledError:
                raise
            except Exception as error:
                log.warning(
                    "NapCat 连接中断：%s；%.1f 秒后重试。",
                    error,
                    settings.reconnect_seconds,
                )
                await asyncio.sleep(settings.reconnect_seconds)
    finally:
        from src.chat.services.ai.service import ai_service

        await ai_service.close()


def main() -> int:
    load_dotenv()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    try:
        settings = load_qq_settings()
        asyncio.run(run_qq_bot(settings))
    except QQConfigurationError as error:
        log.error("QQ 骰娘未启动：%s", error)
        return 2
    except KeyboardInterrupt:
        log.info("QQ 骰娘已停止。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
