"""Platform-independent traditional command boundary."""

from .runtime import (
    CommandHandler,
    CommandInfo,
    CommandRegistry,
    CommandRequest,
    CommandResult,
    normalize_command_text,
    register_help_command,
)

__all__ = [
    "CommandHandler",
    "CommandInfo",
    "CommandRegistry",
    "CommandRequest",
    "CommandResult",
    "normalize_command_text",
    "register_help_command",
]
