"""OneBot 11 / NapCat adapter boundary."""

from .event_mapper import (
    is_bot_addressed,
    is_supported_message_event,
    map_onebot_message,
)

__all__ = [
    "is_bot_addressed",
    "is_supported_message_event",
    "map_onebot_message",
]
