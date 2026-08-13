"""Platform-neutral contracts used by the chat pipeline."""

from .models import (
    ConversationContext,
    ConversationKind,
    IncomingMessage,
    MessageImage,
    RepliedMessage,
    ThreadContext,
)
from .request_context import PlatformRequestContext

__all__ = [
    "ConversationContext",
    "ConversationKind",
    "IncomingMessage",
    "MessageImage",
    "PlatformRequestContext",
    "RepliedMessage",
    "ThreadContext",
]
