import base64
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import aiohttp
import pytest

from src.chat.platform import (
    ConversationContext,
    ConversationKind,
    IncomingMessage,
    MessageFile,
)
from src.chat.platform.onebot.file_transfer import (
    OneBotFileError,
    OneBotIncomingFileProvider,
    RecentMessageFileStore,
)
from src.chat.platform.onebot.transport import OneBotWebSocketClient


@pytest.mark.asyncio
async def test_file_provider_uses_get_file_base64_fallback() -> None:
    client = SimpleNamespace(
        get_file=AsyncMock(
            return_value={"base64": base64.b64encode(b"xlsx-bytes").decode()}
        )
    )
    provider = OneBotIncomingFileProvider(client)

    payload = await provider.read(
        MessageFile(file_id="file-1", name="card.xlsx"),
        max_bytes=1024,
    )

    assert payload == b"xlsx-bytes"
    client.get_file.assert_awaited_once_with("file-1")


@pytest.mark.asyncio
async def test_file_provider_rejects_declared_oversize_before_api_call() -> None:
    client = SimpleNamespace(get_file=AsyncMock())
    provider = OneBotIncomingFileProvider(client)

    with pytest.raises(OneBotFileError, match="文件过大"):
        await provider.read(
            MessageFile(file_id="file-1", name="card.xlsx", size=2048),
            max_bytes=1024,
        )

    client.get_file.assert_not_awaited()


def test_recent_file_store_is_scoped_to_user_and_conversation() -> None:
    store = RecentMessageFileStore()
    file = MessageFile(file_id="file-1", name="card.xlsx")
    first = IncomingMessage(
        platform="qq",
        message_id="1",
        user_id="10001",
        user_name="玩家甲",
        text="",
        conversation=ConversationContext("group-1", ConversationKind.GROUP),
        files=(file,),
    )
    same_user_next_message = IncomingMessage(
        platform="qq",
        message_id="2",
        user_id="10001",
        user_name="玩家甲",
        text=".pc import",
        conversation=ConversationContext("group-1", ConversationKind.GROUP),
    )
    other_user = IncomingMessage(
        platform="qq",
        message_id="3",
        user_id="20002",
        user_name="玩家乙",
        text=".pc import",
        conversation=ConversationContext("group-1", ConversationKind.GROUP),
    )

    store.remember(first)

    assert store.latest(same_user_next_message) == (file,)
    assert store.latest(other_user) == ()


@pytest.mark.asyncio
async def test_get_file_action_buffers_interleaved_event() -> None:
    client = OneBotWebSocketClient("ws://127.0.0.1:3001", "token")

    class FakeWebSocket:
        closed = False

        def __init__(self):
            self.sent = []
            self.receive_count = 0

        async def send_json(self, payload):
            self.sent.append(payload)

        async def receive(self):
            self.receive_count += 1
            if self.receive_count == 1:
                payload = {
                    "post_type": "message",
                    "message_type": "private",
                    "message_id": 1,
                }
            else:
                payload = {
                    "status": "ok",
                    "retcode": 0,
                    "data": {"url": "https://example.invalid/card.xlsx"},
                    "echo": self.sent[0]["echo"],
                }
            return SimpleNamespace(
                type=aiohttp.WSMsgType.TEXT,
                data=json.dumps(payload),
            )

    websocket = FakeWebSocket()
    client._websocket = websocket

    info = await client.get_file("file-1")
    events = client.events()
    buffered_event = await anext(events)
    await events.aclose()

    assert info["url"].endswith("card.xlsx")
    assert websocket.sent[0]["action"] == "get_file"
    assert websocket.sent[0]["params"] == {"file_id": "file-1"}
    assert buffered_event["message_id"] == 1
