"""Convert OneBot 11 message events into platform-neutral chat messages."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
import re
from typing import Any

from src.chat.platform.models import (
    ConversationContext,
    ConversationKind,
    IncomingMessage,
    RepliedMessage,
)


_CQ_AT_PATTERN = re.compile(r"\[CQ:at,qq=([^,\]]+)[^\]]*\]")
_CQ_REPLY_PATTERN = re.compile(r"\[CQ:reply,id=([^,\]]+)[^\]]*\]")
_CQ_IMAGE_PATTERN = re.compile(r"\[CQ:image,[^\]]*\]")
_CQ_OTHER_PATTERN = re.compile(r"\[CQ:[^\]]+\]")


def _string(value: Any, default: str = "") -> str:
    return default if value is None else str(value)


def _segments(event: Mapping[str, Any]) -> Sequence[Mapping[str, Any]]:
    message = event.get("message")
    if not isinstance(message, Sequence) or isinstance(message, (str, bytes)):
        return ()
    return tuple(segment for segment in message if isinstance(segment, Mapping))


def is_supported_message_event(event: Mapping[str, Any]) -> bool:
    """Accept incoming group/private messages, but never the bot's own messages."""

    if event.get("post_type") != "message":
        return False
    if event.get("message_type") not in {"group", "private"}:
        return False
    return _string(event.get("user_id")) != _string(event.get("self_id"))


def is_bot_addressed(event: Mapping[str, Any]) -> bool:
    """Private messages always address the bot; group messages must @ it."""

    if not is_supported_message_event(event):
        return False
    if event.get("message_type") == "private":
        return True

    self_id = _string(event.get("self_id"))
    for segment in _segments(event):
        if segment.get("type") == "at":
            data = segment.get("data")
            if isinstance(data, Mapping) and _string(data.get("qq")) == self_id:
                return True

    raw_message = _string(event.get("raw_message") or event.get("message"))
    return any(mentioned_id == self_id for mentioned_id in _CQ_AT_PATTERN.findall(raw_message))


def _sender_name(event: Mapping[str, Any]) -> str:
    sender = event.get("sender")
    if isinstance(sender, Mapping):
        return _string(sender.get("card") or sender.get("nickname"))
    return ""


def _message_text_from_segments(event: Mapping[str, Any]) -> tuple[str, str | None]:
    text_parts: list[str] = []
    reply_id: str | None = None
    self_id = _string(event.get("self_id"))

    for segment in _segments(event):
        segment_type = segment.get("type")
        data = segment.get("data")
        data = data if isinstance(data, Mapping) else {}

        if segment_type == "text":
            text_parts.append(_string(data.get("text")))
        elif segment_type == "at":
            mentioned_id = _string(data.get("qq"))
            if mentioned_id and mentioned_id != self_id:
                text_parts.append("@全体成员" if mentioned_id == "all" else f"@{mentioned_id}")
        elif segment_type == "reply":
            reply_id = _string(data.get("id")) or reply_id
        elif segment_type == "image":
            text_parts.append("[图片]")
        elif segment_type == "face":
            face_id = _string(data.get("id"))
            text_parts.append(f"[QQ表情:{face_id}]" if face_id else "[QQ表情]")

    return "".join(text_parts).strip(), reply_id


def _message_text_from_cq(event: Mapping[str, Any]) -> tuple[str, str | None]:
    raw_message = _string(event.get("raw_message") or event.get("message"))
    self_id = _string(event.get("self_id"))
    reply_match = _CQ_REPLY_PATTERN.search(raw_message)

    def replace_at(match: re.Match[str]) -> str:
        mentioned_id = match.group(1)
        if mentioned_id == self_id:
            return ""
        return "@全体成员" if mentioned_id == "all" else f"@{mentioned_id}"

    text = _CQ_AT_PATTERN.sub(replace_at, raw_message)
    text = _CQ_REPLY_PATTERN.sub("", text)
    text = _CQ_IMAGE_PATTERN.sub("[图片]", text)
    text = _CQ_OTHER_PATTERN.sub("", text)
    return text.strip(), reply_match.group(1) if reply_match else None


def _conversation(event: Mapping[str, Any], user_name: str) -> ConversationContext:
    if event.get("message_type") == "group":
        group_id = _string(event.get("group_id"))
        group_name = _string(event.get("group_name"), f"QQ群 {group_id}")
        return ConversationContext(
            conversation_id=group_id,
            kind=ConversationKind.GROUP,
            name=group_name,
            space_id=group_id,
            space_name=group_name,
        )

    user_id = _string(event.get("user_id"))
    return ConversationContext(
        conversation_id=user_id,
        kind=ConversationKind.DIRECT,
        name=user_name,
    )


def map_onebot_message(event: Mapping[str, Any]) -> IncomingMessage:
    """Translate one NapCat OneBot 11 message event into ``IncomingMessage``."""

    if not is_supported_message_event(event):
        raise ValueError("不是受支持的 OneBot 11 入站消息事件")

    user_id = _string(event.get("user_id"))
    user_name = _sender_name(event) or user_id
    if _segments(event):
        text, reply_id = _message_text_from_segments(event)
    else:
        text, reply_id = _message_text_from_cq(event)

    timestamp_value = event.get("time")
    timestamp = None
    if isinstance(timestamp_value, (int, float)):
        timestamp = datetime.fromtimestamp(timestamp_value, tz=timezone.utc)

    replied_message = (
        RepliedMessage(message_id=reply_id) if reply_id is not None else None
    )

    return IncomingMessage(
        platform="qq",
        message_id=_string(event.get("message_id")),
        user_id=user_id,
        user_name=user_name,
        text=text,
        conversation=_conversation(event, user_name),
        timestamp=timestamp,
        replied_message=replied_message,
    )
