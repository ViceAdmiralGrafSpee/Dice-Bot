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
    r"(?<![A-Za-z0-9_])(?:\d{0,3})[dD]\d{1,5}(?:\s*[+-]\s*\d+)?"
    r"(?![A-Za-z0-9_])"
)
# A message that names a DND 5e (2014) rule check should be routed to the
# dnd5e_check tool, never to the generic dice roller.
_DND5E_RULE_PATTERN = re.compile(
    r"(?:d\s*&\s*d|dnd|龙与地下城)\s*"
    r"(?:5\s*e|第五版|2014(?:\s*版)?)"
    r"|(?:5\s*e|第五版|2014(?:\s*版)?).{0,8}"
    r"(?:d\s*&\s*d|dnd|龙与地下城)",
    re.IGNORECASE,
)
_DND5E_CHECK_KEYWORD_PATTERN = re.compile(
    r"检定|攻击|豁免|优势|劣势",
    re.IGNORECASE,
)
_DICE_INTENT_PATTERN = re.compile(
    r"骰一下|骰一个|骰个|掷骰|投骰|丢骰|扔骰|摇骰|重骰|"
    r"检定|判定|抽签|随机(?:数|一下|决定|选择|抽取)|"
    r"(?:^|[^A-Za-z])roll(?:$|[^A-Za-z])",
    re.IGNORECASE,
)
_REQUEST_PATTERN = re.compile(r"帮|请|给我|来(?:个|一次|一下)?|看看|测|算|决定")


def message_requests_dice(text: str) -> bool:
    """Return whether the current user message explicitly asks for randomness."""

    normalized = text.strip()
    if not normalized:
        return False
    if _DND5E_RULE_PATTERN.search(normalized) and _DND5E_CHECK_KEYWORD_PATTERN.search(
        normalized
    ):
        return False
    if _DICE_INTENT_PATTERN.search(normalized):
        return True
    if re.search(r"骰(?:子|$|[\s，。！？!?])|色子", normalized) and _REQUEST_PATTERN.search(
        normalized
    ):
        return True

    expression = _DICE_EXPRESSION_PATTERN.search(normalized)
    if expression is None:
        return False
    without_expression = (
        normalized[: expression.start()] + normalized[expression.end() :]
    ).strip(" \t\r\n，。！？!?：:；;、（）()[]【】")
    return not without_expression or bool(_REQUEST_PATTERN.search(without_expression))


def create_roll_dice_tool(engine: DiceEngine | None = None) -> ToolDefinition:
    dice_engine = engine or DiceEngine()

    async def roll_dice(
        arguments: Mapping[str, Any],
        _context: ToolExecutionContext,
    ) -> ToolOutcome:
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
            "实际掷骰。只有当前用户消息明确要求随机掷骰、检定，或以请求语气给出"
            "骰子表达式时才调用；普通叙述、关卡编号、算术数字以及更早对话中提过"
            "骰子，都不能作为本轮调用理由。"
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
        availability=lambda context: (
            context.user_text is None or message_requests_dice(context.user_text)
        ),
    )


def register_dice_tools(
    registry: ToolRegistry,
    engine: DiceEngine | None = None,
) -> None:
    registry.register(create_roll_dice_tool(engine))
