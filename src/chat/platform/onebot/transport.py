"""Minimal forward WebSocket transport for NapCat OneBot 11."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Mapping
from collections import deque
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
        self._buffered_events: deque[dict[str, Any]] = deque()
        self._action_lock = asyncio.Lock()

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
            self._buffered_events.clear()
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
        self._buffered_events.clear()

    async def __aenter__(self) -> OneBotWebSocketClient:
        await self.connect()
        return self

    async def __aexit__(self, *_args: Any) -> None:
        await self.close()

    async def events(self) -> AsyncIterator[dict[str, Any]]:
        """Yield event objects and silently skip API responses and invalid JSON."""

        if not self.connected or self._websocket is None:
            raise RuntimeError("OneBot WebSocket 尚未连接")

        while self.connected:
            if self._buffered_events:
                yield self._buffered_events.popleft()
                continue
            message = await self._websocket.receive()
            payload = self._decode_message(message)
            if payload is None:
                if message.type in {
                    aiohttp.WSMsgType.CLOSE,
                    aiohttp.WSMsgType.CLOSED,
                    aiohttp.WSMsgType.ERROR,
                }:
                    break
                continue
            if payload.get("post_type"):
                yield payload

    async def send_message(self, event: Mapping[str, Any], text: str) -> None:
        if not self.connected or self._websocket is None:
            raise RuntimeError("OneBot WebSocket 尚未连接")
        await self._websocket.send_json(build_send_message_action(event, text))

    async def call_action(
        self,
        action: str,
        params: Mapping[str, Any],
        *,
        timeout_seconds: float = 30.0,
    ) -> Mapping[str, Any]:
        """Call one API while preserving events that arrive before its echo."""

        if not self.connected or self._websocket is None:
            raise RuntimeError("OneBot WebSocket 尚未连接")
        echo = uuid4().hex
        request = {"action": action, "params": dict(params), "echo": echo}
        async with self._action_lock:
            await self._websocket.send_json(request)
            async with asyncio.timeout(timeout_seconds):
                while True:
                    message = await self._websocket.receive()
                    payload = self._decode_message(message)
                    if payload is None:
                        if message.type in {
                            aiohttp.WSMsgType.CLOSE,
                            aiohttp.WSMsgType.CLOSED,
                            aiohttp.WSMsgType.ERROR,
                        }:
                            raise ConnectionError("等待 OneBot API 响应时连接已关闭")
                        continue
                    if payload.get("post_type"):
                        self._buffered_events.append(payload)
                        continue
                    if str(payload.get("echo", "")) != echo:
                        continue
                    if payload.get("status") != "ok" or not _retcode_is_ok(
                        payload.get("retcode")
                    ):
                        message_text = payload.get("message") or payload.get(
                            "wording"
                        )
                        raise RuntimeError(
                            f"OneBot API {action} 调用失败：{message_text or '未知错误'}"
                        )
                    data = payload.get("data")
                    return data if isinstance(data, Mapping) else {}

    async def get_file(self, file_id: str) -> Mapping[str, Any]:
        return await self.call_action("get_file", {"file_id": file_id})

    @staticmethod
    def _decode_message(message: aiohttp.WSMessage) -> dict[str, Any] | None:
        if message.type is not aiohttp.WSMsgType.TEXT:
            return None
        try:
            payload = json.loads(message.data)
        except (json.JSONDecodeError, TypeError):
            return None
        return payload if isinstance(payload, dict) else None


def _retcode_is_ok(value: Any) -> bool:
    try:
        return int(value) == 0
    except (TypeError, ValueError):
        return False
