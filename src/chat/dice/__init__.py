"""Platform-independent dice engine."""

from .commands import (
    create_roll_command_handler,
    handle_dice_command,
    register_dice_commands,
)
from .engine import DiceEngine, DiceExpressionError, DiceRollResult
from .tool import create_roll_dice_tool, register_dice_tools

__all__ = [
    "DiceEngine",
    "DiceExpressionError",
    "DiceRollResult",
    "create_roll_command_handler",
    "handle_dice_command",
    "register_dice_commands",
    "create_roll_dice_tool",
    "register_dice_tools",
]
