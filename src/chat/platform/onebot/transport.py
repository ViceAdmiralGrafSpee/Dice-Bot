"""Minimal forward WebSocket transport for NapCat OneBot 11."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
import json
from typing import Any
from uuid import uuid4

import aiohttp


def build_send_message_action(
    event: Mapping[str, Any], text: str, *, echo: str | None = None
) -> dict[str, Any]:
    """Build the OneBot action used to answer a group or private message."""

    message = [{"type": "text", "data": {"text": text}}]
    message_type = event.get("message_type")

    if message_type == "group":
        action = "send_group_msg"
        params = {"group_id": str(event["group_id"]), "message": message}
    elif message_type == "private":
        action = "send_private_msg"
        params = {"user_id": str(event["user_id"]), "message": message}
    else:
        raise ValueError("只能回复 OneBot 群聊或私聊消息")

    return {
        "action": action,
        "params": params,
        "echo": echo or uuid4().hex,
    }


class OneBotWebSocketClient:
    """Connect Dice-Bot to a NapCat forward WebSocket server."""

    def __init__(self, url: str, access_token: str | None = None) -> None:
        self.url = url
        self.access_token = access_token
        self._session: aiohttp.ClientSession | None = None
        self._websocket: aiohttp.ClientWebSocketResponse | None = None

    @property
    def connected(self) -> bool:
        return self._websocket is not None and not self._websocket.closed

    async def connect(self) -> None:
        if self.connected:
            return

        headers = {}
        if self.access_token:
            headers["Authorization"] = f"Bearer {self.access_token}"

        self._session = aiohttp.ClientSession()
        try:
            self._websocket = await self._session.ws_connect(
                self.url,
                headers=headers,
                heartbeat=30,
            )
        except Exception:
            await self._session.close()
            self._session = None
            raise

    async def close(self) -> None:
        if self._websocket is not None and not self._websocket.closed:
            await self._websocket.close()
        if self._session is not None and not self._session.closed:
            await self._session.close()
        self._websocket = None
        self._session = None

    async def __aenter__(self) -> OneBotWebSocketClient:
        await self.connect()
        return self

    async def __aexit__(self, *_args: Any) -> None:
        await self.close()

    async def events(self) -> AsyncIterator[dict[str, Any]]:
        """Yield event objects and silently skip API responses and invalid JSON."""

        if not self.connected or self._websocket is None:
            raise RuntimeError("OneBot WebSocket 尚未连接")

        async for message in self._websocket:
            if message.type is aiohttp.WSMsgType.TEXT:
                try:
                    payload = json.loads(message.data)
                except (json.JSONDecodeError, TypeError):
                    continue
                if isinstance(payload, dict) and payload.get("post_type"):
                    yield payload
            elif message.type in {
                aiohttp.WSMsgType.CLOSE,
                aiohttp.WSMsgType.CLOSED,
                aiohttp.WSMsgType.ERROR,
            }:
                break

    async def send_message(self, event: Mapping[str, Any], text: str) -> None:
        if not self.connected or self._websocket is None:
            raise RuntimeError("OneBot WebSocket 尚未连接")
        await self._websocket.send_json(build_send_message_action(event, text))
