"""Register the deterministic dice engine as an LLM-callable tool."""

from __future__ import annotations

from collections.abc import Mapping
import re
from typing import Any

from src.chat.tools import (
    ToolDefinition,
    ToolExecutionContext,
    ToolOutcome,
    ToolRegistry,
)

from .engine import DiceEngine, DiceExpressionError


_DICE_EXPRESSION_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_])\d*[dD]\d+(?:\s*[+-]\s*\d+)?"
)
_EXPLICIT_DICE_TERMS = ("骰", "掷", "擲", "roll", "检定", "檢定", "随机")


def _has_explicit_dice_intent(message_text: str) -> bool:
    lowered = message_text.lower()
    return bool(_DICE_EXPRESSION_PATTERN.search(lowered)) or any(
        term in lowered for term in _EXPLICIT_DICE_TERMS
    )


def create_roll_dice_tool(engine: DiceEngine | None = None) -> ToolDefinition:
    dice_engine = engine or DiceEngine()

    async def roll_dice(
        arguments: Mapping[str, Any],
        context: ToolExecutionContext,
    ) -> ToolOutcome:
        if (
            context.message_text is not None
            and not _has_explicit_dice_intent(context.message_text)
        ):
            raise DiceExpressionError("用户没有明确要求掷骰，已拒绝生成随机结果")

        expression = arguments.get("expression")
        if not isinstance(expression, str) or not expression.strip():
            raise DiceExpressionError("expression 必须是非空骰子表达式")

        result = dice_engine.roll(expression)
        return ToolOutcome(
            data={
                "notation": result.notation,
                "rolls": list(result.rolls),
                "modifier": result.modifier,
                "total": result.total,
            },
            authoritative_output=result.format(),
        )

    return ToolDefinition(
        name="roll_dice",
        description=(
            "实际掷骰。用户要求随机掷骰、检定或明确给出骰子表达式时必须调用；"
            "绝对不要自行编造骰面、总数或随机结果。工具结果中的数值是权威结果，"
            "只能如实解释，不能修改。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "expression": {
                    "type": "string",
                    "description": "标准骰子表达式，例如 1d100、2d6+3、d20-1",
                }
            },
            "required": ["expression"],
            "additionalProperties": False,
        },
        handler=roll_dice,
        category="dice",
    )


def register_dice_tools(
    registry: ToolRegistry,
    engine: DiceEngine | None = None,
) -> None:
    registry.register(create_roll_dice_tool(engine))
