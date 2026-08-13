"""Expose authoritative D&D 5e (2014) checks to the LLM tool runtime."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from src.chat.tools import (
    ToolDefinition,
    ToolExecutionContext,
    ToolOutcome,
    ToolRegistry,
)

from .engine import D20RollMode, Dnd5eCheckError, Dnd5eEngine


def create_dnd5e_check_tool(engine: Dnd5eEngine | None = None) -> ToolDefinition:
    dnd5e_engine = engine or Dnd5eEngine()

    async def dnd5e_check(
        arguments: Mapping[str, Any],
        _context: ToolExecutionContext,
    ) -> ToolOutcome:
        unexpected_arguments = set(arguments) - {"mode", "modifier"}
        if unexpected_arguments:
            raise Dnd5eCheckError("只接受 mode 和 modifier 参数")

        mode_value = arguments.get("mode", D20RollMode.NORMAL.value)
        if not isinstance(mode_value, str):
            raise Dnd5eCheckError("mode 必须是字符串")
        try:
            mode = D20RollMode(mode_value)
        except ValueError as error:
            raise Dnd5eCheckError(
                "mode 必须是 normal、advantage 或 disadvantage"
            ) from error

        modifier = arguments.get("modifier", 0)
        if not isinstance(modifier, int) or isinstance(modifier, bool):
            raise Dnd5eCheckError("modifier 必须是整数")

        result = dnd5e_engine.check(modifier=modifier, mode=mode)
        return ToolOutcome(
            data={
                "ruleset": "dnd5e",
                "mode": result.mode.value,
                "rolls": list(result.rolls),
                "selected_roll": result.selected_roll,
                "modifier": result.modifier,
                "total": result.total,
            },
            authoritative_output=result.format(),
        )

    return ToolDefinition(
        name="dnd5e_check",
        description=(
            "执行 Dungeons & Dragons 5e（2014 版）d20 检定。用户明确要求 DND "
            "5e/2014 版的普通、优势或劣势检定时调用。骰值、取高/取低和总值均由 "
            "Python 决定，不得编造或修改。当前没有角色卡数据：modifier 只能使用用户"
            "明确给出的整数；用户未给出时必须使用 0，不得猜测属性、熟练或其他加值。"
            "本工具不接收 DC；没有其他权威规则信息时，不得自行宣判成功、失败、重击"
            "或大失败。不得用于 2024 修订版（dnd5r）。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "mode": {
                    "type": "string",
                    "enum": ["normal", "advantage", "disadvantage"],
                    "description": "普通、优势或劣势检定；用户未指定时使用 normal",
                },
                "modifier": {
                    "type": "integer",
                    "description": "用户明确给出的检定加减值；未给出时使用 0",
                },
            },
            "additionalProperties": False,
        },
        handler=dnd5e_check,
        category="dnd5e",
    )


def register_dnd5e_tools(
    registry: ToolRegistry,
    engine: Dnd5eEngine | None = None,
) -> None:
    registry.register(create_dnd5e_check_tool(engine))
