"""Convert processed Discord messages into platform-neutral values."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import discord

from src.chat.platform.models import (
    ConversationContext,
    ConversationKind,
    IncomingMessage,
    MessageImage,
    RepliedMessage,
    ThreadContext,
)


def _optional_id(value: Any) -> str | None:
    return str(value) if value is not None else None


def _display_name(value: Any) -> str | None:
    if value is None:
        return None
    return getattr(value, "display_name", None) or getattr(value, "name", None)


def _map_images(processed_data: Mapping[str, Any]) -> tuple[MessageImage, ...]:
    return tuple(
        MessageImage(
            mime_type=image["mime_type"],
            data=bytes(image["data"]),
            source=image.get("source", "attachment"),
            name=image.get("name"),
        )
        for image in processed_data.get("image_data_list", ())
    )


def _map_reply(
    message: discord.Message, processed_data: Mapping[str, Any]
) -> RepliedMessage | None:
    reference = message.reference
    reply_id = getattr(reference, "message_id", None) if reference else None
    if reply_id is None:
        return None

    cached_message = getattr(reference, "cached_message", None)
    cached_author = getattr(cached_message, "author", None)

    return RepliedMessage(
        message_id=str(reply_id),
        user_id=_optional_id(getattr(cached_author, "id", None)),
        user_name=_display_name(cached_author),
        text=processed_data.get("replied_content", ""),
    )


def _map_conversation(message: discord.Message) -> ConversationContext:
    channel = message.channel
    guild = message.guild
    space_id = _optional_id(getattr(guild, "id", None))
    space_name = getattr(guild, "name", None)

    if isinstance(channel, discord.Thread):
        owner = getattr(channel, "owner", None)
        parent = getattr(channel, "parent", None)
        starter_message = getattr(channel, "starter_message", None)

        thread_context = ThreadContext(
            owner_id=_optional_id(
                getattr(channel, "owner_id", None)
                or getattr(owner, "id", None)
            ),
            owner_name=_display_name(owner),
            parent_id=_optional_id(
                getattr(channel, "parent_id", None)
                or getattr(parent, "id", None)
            ),
            parent_name=getattr(parent, "name", None),
            tags=tuple(
                tag.name
                for tag in getattr(channel, "applied_tags", ())
                if getattr(tag, "name", None)
            ),
            starter_text=getattr(starter_message, "content", None),
        )
        return ConversationContext(
            conversation_id=str(channel.id),
            kind=ConversationKind.THREAD,
            name=getattr(channel, "name", ""),
            space_id=space_id,
            space_name=space_name,
            thread=thread_context,
        )

    if isinstance(channel, discord.GroupChannel):
        kind = ConversationKind.GROUP
    elif guild is None:
        kind = ConversationKind.DIRECT
    else:
        kind = ConversationKind.CHANNEL

    channel_name = getattr(channel, "name", None)
    if not channel_name and kind is ConversationKind.DIRECT:
        channel_name = _display_name(getattr(channel, "recipient", None)) or "私信"

    return ConversationContext(
        conversation_id=str(channel.id),
        kind=kind,
        name=channel_name or "",
        space_id=space_id,
        space_name=space_name,
    )


def map_discord_message(
    message: discord.Message, processed_data: Mapping[str, Any]
) -> IncomingMessage:
    """Translate existing MessageProcessor output without changing its behavior."""

    return IncomingMessage(
        platform="discord",
        message_id=str(message.id),
        user_id=str(message.author.id),
        user_name=message.author.display_name,
        text=processed_data.get("user_content", ""),
        conversation=_map_conversation(message),
        timestamp=message.created_at,
        replied_message=_map_reply(message, processed_data),
        images=_map_images(processed_data),
    )
