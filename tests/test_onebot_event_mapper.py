from datetime import datetime, timezone

import pytest

from src.chat.platform.models import ConversationKind
from src.chat.platform.onebot.event_mapper import (
    is_bot_addressed,
    is_supported_message_event,
    map_onebot_message,
)


def test_maps_group_message_and_removes_bot_mention() -> None:
    event = {
        "time": 1_700_000_000,
        "self_id": "90001",
        "post_type": "message",
        "message_type": "group",
        "message_id": "30003",
        "group_id": "20002",
        "user_id": "10001",
        "sender": {"nickname": "调查员", "card": "守密人"},
        "message": [
            {"type": "at", "data": {"qq": "90001"}},
            {"type": "text", "data": {"text": " 骰 2d6+3"}},
        ],
        "raw_message": "[CQ:at,qq=90001] 骰 2d6+3",
    }

    assert is_bot_addressed(event) is True
    incoming = map_onebot_message(event)

    assert incoming.platform == "qq"
    assert incoming.message_id == "30003"
    assert incoming.user_id == "10001"
    assert incoming.user_name == "守密人"
    assert incoming.text == "骰 2d6+3"
    assert incoming.conversation.kind is ConversationKind.GROUP
    assert incoming.conversation.conversation_id == "20002"
    assert incoming.conversation.space_id == "20002"
    assert incoming.timestamp == datetime.fromtimestamp(
        1_700_000_000, tz=timezone.utc
    )


def test_maps_private_reply_and_image_placeholder() -> None:
    event = {
        "self_id": 90001,
        "post_type": "message",
        "message_type": "private",
        "message_id": 30004,
        "user_id": 10001,
        "sender": {"nickname": "调查员"},
        "message": [
            {"type": "reply", "data": {"id": "29999"}},
            {"type": "text", "data": {"text": "看看这个"}},
            {"type": "image", "data": {"url": "https://example.invalid/a.png"}},
        ],
    }

    assert is_bot_addressed(event) is True
    incoming = map_onebot_message(event)

    assert incoming.text == "看看这个[图片]"
    assert incoming.replied_message is not None
    assert incoming.replied_message.message_id == "29999"
    assert incoming.conversation.kind is ConversationKind.DIRECT
    assert incoming.conversation.conversation_id == "10001"


def test_maps_napcat_file_segment_without_loading_bytes() -> None:
    event = {
        "self_id": 90001,
        "post_type": "message",
        "message_type": "private",
        "message_id": 30006,
        "user_id": 10001,
        "sender": {"nickname": "玩家"},
        "message": [
            {
                "type": "file",
                "data": {
                    "file": "角色卡.xlsx",
                    "file_id": "file-uuid",
                    "file_size": "4096",
                    "url": "https://example.invalid/card.xlsx",
                },
            }
        ],
    }

    incoming = map_onebot_message(event)

    assert incoming.text == ""
    assert len(incoming.files) == 1
    assert incoming.files[0].name == "角色卡.xlsx"
    assert incoming.files[0].file_id == "file-uuid"
    assert incoming.files[0].size == 4096
    assert incoming.files[0].url == "https://example.invalid/card.xlsx"


def test_supports_cq_string_messages() -> None:
    event = {
        "self_id": "90001",
        "post_type": "message",
        "message_type": "group",
        "message_id": "30005",
        "group_id": "20002",
        "user_id": "10001",
        "sender": {"nickname": "调查员"},
        "message": "[CQ:at,qq=90001] 检查门锁[CQ:image,file=x]",
        "raw_message": "[CQ:at,qq=90001] 检查门锁[CQ:image,file=x]",
    }

    assert is_bot_addressed(event) is True
    assert map_onebot_message(event).text == "检查门锁[图片]"


@pytest.mark.parametrize(
    "event",
    [
        {"post_type": "meta_event", "self_id": "1"},
        {
            "post_type": "message_sent",
            "message_type": "group",
            "self_id": "1",
            "user_id": "1",
        },
        {
            "post_type": "message",
            "message_type": "group",
            "self_id": "1",
            "user_id": "1",
        },
    ],
)
def test_rejects_non_incoming_message_events(event: dict) -> None:
    assert is_supported_message_event(event) is False
    assert is_bot_addressed(event) is False
    with pytest.raises(ValueError):
        map_onebot_message(event)
