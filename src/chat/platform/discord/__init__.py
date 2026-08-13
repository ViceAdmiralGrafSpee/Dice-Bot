"""Discord-specific adapters for the platform-neutral chat boundary."""

from .message_mapper import map_discord_message
from .request_context import DiscordRequestContext

__all__ = ["DiscordRequestContext", "map_discord_message"]
