"""Platform-independent dice engine."""

from .commands import handle_dice_command
from .engine import DiceEngine, DiceExpressionError, DiceRollResult
from .tool import create_roll_dice_tool, register_dice_tools

__all__ = [
    "DiceEngine",
    "DiceExpressionError",
    "DiceRollResult",
    "handle_dice_command",
    "create_roll_dice_tool",
    "register_dice_tools",
]
