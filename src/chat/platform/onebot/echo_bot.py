"""Local smoke test: @ the QQ bot and receive a fixed response."""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Mapping

from dotenv import load_dotenv

from .event_mapper import is_bot_addressed, map_onebot_message
from .transport import OneBotWebSocketClient


log = logging.getLogger(__name__)
ECHO_RESPONSE = "收到。QQ / NapCat / OneBot 通道已经连通。"


async def handle_echo_event(
    client: OneBotWebSocketClient, event: Mapping[str, Any]
) -> bool:
    """Reply only to private messages or group messages that mention the bot."""

    if not is_bot_addressed(event):
        return False

    incoming = map_onebot_message(event)
    log.info(
        "收到 QQ 消息：用户=%s 会话=%s 文本=%r",
        incoming.user_id,
        incoming.conversation.conversation_id,
        incoming.text,
    )
    await client.send_message(event, ECHO_RESPONSE)
    return True


async def run_echo_bot() -> None:
    load_dotenv()
    url = os.getenv("ONEBOT_WS_URL", "ws://127.0.0.1:3001")
    access_token = os.getenv("ONEBOT_ACCESS_TOKEN") or None
    reconnect_seconds = 5

    while True:
        client = OneBotWebSocketClient(url, access_token)
        try:
            log.info("正在连接本机 NapCat OneBot WebSocket：%s", url)
            async with client:
                log.info("OneBot WebSocket 已连接，可以在 QQ 中 @机器人测试。")
                async for event in client.events():
                    await handle_echo_event(client, event)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            log.warning(
                "OneBot 连接中断：%s；%s 秒后重试。",
                error,
                reconnect_seconds,
            )
            await asyncio.sleep(reconnect_seconds)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        asyncio.run(run_echo_bot())
    except KeyboardInterrupt:
        log.info("OneBot 本地回声测试已停止。")


if __name__ == "__main__":
    main()
