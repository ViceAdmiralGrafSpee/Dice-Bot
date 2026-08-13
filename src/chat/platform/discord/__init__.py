"""Discord-specific adapters for the platform-neutral chat boundary."""

from .message_mapper import map_discord_message

__all__ = ["map_discord_message"]
