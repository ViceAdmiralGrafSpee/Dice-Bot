"""Text command boundary for the platform-independent dice engine."""

from __future__ import annotations

import re

from .engine import DiceEngine, DiceExpressionError


_COMMAND_PATTERN = re.compile(
    r"^\.(?:r|roll)(?=$|\s|\d|[dD])",
    flags=re.IGNORECASE,
)


def handle_dice_command(text: str, engine: DiceEngine) -> str | None:
    """Return a dice response, or ``None`` when text is not a dice command."""

    stripped = text.strip()
    command_match = _COMMAND_PATTERN.match(stripped)
    if command_match is None:
        return None

    expression = stripped[command_match.end() :].strip()
    if not expression:
        return "骰子命令格式：.r 1d100 或 .r 2d6+3"

    try:
        return engine.roll(expression).format()
    except DiceExpressionError as error:
        return f"骰子命令有误：{error}"
