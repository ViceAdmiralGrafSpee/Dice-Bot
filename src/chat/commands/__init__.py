"""Platform-independent traditional command boundary."""

from .runtime import (
    CommandHandler,
    CommandRegistry,
    CommandRequest,
    CommandResult,
)

__all__ = [
    "CommandHandler",
    "CommandRegistry",
    "CommandRequest",
    "CommandResult",
]
