"""OneBot 11 / NapCat adapter boundary."""

from .chat_gateway import handle_onebot_chat_event
from .event_mapper import (
    is_bot_addressed,
    is_supported_message_event,
    map_onebot_message,
)
from .request_context import OneBotRequestContext

__all__ = [
    "OneBotRequestContext",
    "handle_onebot_chat_event",
    "is_bot_addressed",
    "is_supported_message_event",
    "map_onebot_message",
]
