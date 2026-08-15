"""Traditional commands for the D&D 5e (2014) rule plugin."""

from __future__ import annotations

import re

from src.chat.commands import (
    CommandHandler,
    CommandRegistry,
    CommandRequest,
    CommandResult,
)

from .action import Dnd5eCheckAction, Dnd5eCheckRequest
from .engine import D20RollMode, Dnd5eCheckError, Dnd5eEngine


_MODIFIER_PATTERN = re.compile(r"^[+-]?\d+$")
_MODE_NAMES = {
    "adv": D20RollMode.ADVANTAGE,
    "advantage": D20RollMode.ADVANTAGE,
    "优势": D20RollMode.ADVANTAGE,
    "dis": D20RollMode.DISADVANTAGE,
    "disadvantage": D20RollMode.DISADVANTAGE,
    "劣势": D20RollMode.DISADVANTAGE,
}
_USAGE = (
    "DND 5e 命令格式：.dnd5e check [加值]，或 "
    ".dnd5e check <adv|dis> [加值]"
)


def create_dnd5e_command_handler(
    action: Dnd5eCheckAction,
) -> CommandHandler:
    """Build the version-specific D&D 5e command handler."""

    async def handle_dnd5e(request: CommandRequest) -> CommandResult:
        parts = request.arguments.split()
        if not parts or parts[0].lower() != "check":
            return CommandResult(_USAGE)

        arguments = parts[1:]
        mode = D20RollMode.NORMAL
        if arguments and arguments[0].lower() in _MODE_NAMES:
            mode = _MODE_NAMES[arguments.pop(0).lower()]

        if len(arguments) > 1:
            return CommandResult(_USAGE)

        modifier_text = arguments[0] if arguments else "0"
        if _MODIFIER_PATTERN.fullmatch(modifier_text) is None:
            return CommandResult(_USAGE)

        try:
            result = await action.execute(
                Dnd5eCheckRequest(
                    modifier=int(modifier_text),
                    mode=mode,
                ),
                request.context,
            )
        except Dnd5eCheckError as error:
            return CommandResult(f"DND 5e 检定有误：{error}")
        return CommandResult(result.authoritative_output or "DND 5e 检定已完成")

    return handle_dnd5e


def register_dnd5e_commands(
    registry: CommandRegistry,
    engine: Dnd5eEngine | None = None,
    *,
    action: Dnd5eCheckAction | None = None,
) -> None:
    """Register only the explicit ``.dnd5e`` edition command."""

    registry.register(
        "dnd5e",
        create_dnd5e_command_handler(
            action or Dnd5eCheckAction(engine or Dnd5eEngine())
        ),
    )
