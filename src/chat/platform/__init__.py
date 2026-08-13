"""Platform-neutral contracts used by the chat pipeline."""

from .models import (
    ConversationContext,
    ConversationKind,
    IncomingMessage,
    MessageImage,
    RepliedMessage,
    ThreadContext,
)

__all__ = [
    "ConversationContext",
    "ConversationKind",
    "IncomingMessage",
    "MessageImage",
    "RepliedMessage",
    "ThreadContext",
]
