"""Platform-neutral message models for the core chat boundary.

Adapters are responsible for converting Discord, OneBot, or other platform
events into these immutable values.  No platform SDK object belongs here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class ConversationKind(str, Enum):
    """Kinds of conversations understood by the chat core."""

    DIRECT = "direct"
    GROUP = "group"
    CHANNEL = "channel"
    THREAD = "thread"


@dataclass(frozen=True, slots=True)
class MessageImage:
    """An image already read by a platform adapter."""

    mime_type: str
    data: bytes
    source: str = "attachment"
    name: str | None = None


@dataclass(frozen=True, slots=True)
class RepliedMessage:
    """The normalized message referenced by a reply, when available."""

    message_id: str
    user_id: str | None = None
    user_name: str | None = None
    text: str = ""
    images: tuple[MessageImage, ...] = ()


@dataclass(frozen=True, slots=True)
class ThreadContext:
    """Optional thread metadata currently used by prompts and tool settings."""

    owner_id: str | None = None
    owner_name: str | None = None
    parent_id: str | None = None
    parent_name: str | None = None
    tags: tuple[str, ...] = ()
    starter_text: str | None = None


@dataclass(frozen=True, slots=True)
class ConversationContext:
    """Where a message happened, without exposing a platform channel object."""

    conversation_id: str
    kind: ConversationKind
    name: str = ""
    space_id: str | None = None
    space_name: str | None = None
    thread: ThreadContext | None = None


@dataclass(frozen=True, slots=True)
class IncomingMessage:
    """Normalized input accepted by the future platform-independent chat core."""

    platform: str
    message_id: str
    user_id: str
    user_name: str
    text: str
    conversation: ConversationContext
    timestamp: datetime | None = None
    replied_message: RepliedMessage | None = None
    images: tuple[MessageImage, ...] = ()
