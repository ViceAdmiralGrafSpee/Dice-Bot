"""Register traditional dice commands with the command runtime."""

from __future__ import annotations

from src.chat.commands import (
    CommandHandler,
    CommandRegistry,
    CommandRequest,
    CommandResult,
)

from .engine import DiceEngine, DiceExpressionError


def create_roll_command_handler(
    engine: DiceEngine,
) -> CommandHandler:
    """Build a direct command handler backed by the Python dice engine."""

    def handle_roll(request: CommandRequest) -> CommandResult:
        if not request.arguments:
            return CommandResult("骰子命令格式：.r 1d100 或 .r 2d6+3")

        try:
            content = engine.roll(request.arguments).format()
        except DiceExpressionError as error:
            content = f"骰子命令有误：{error}"
        return CommandResult(content)

    return handle_roll


def register_dice_commands(
    registry: CommandRegistry,
    engine: DiceEngine | None = None,
) -> None:
    """Register ``.r`` and its existing ``.roll`` alias."""

    registry.register(
        "r",
        create_roll_command_handler(engine or DiceEngine()),
        aliases=("roll",),
    )


async def handle_dice_command(text: str, engine: DiceEngine) -> str | None:
    """Compatibility wrapper around the shared command registry."""

    registry = CommandRegistry()
    register_dice_commands(registry, engine)
    result = await registry.dispatch(text)
    return None if result is None else result.content
