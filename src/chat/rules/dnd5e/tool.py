"""Expose authoritative D&D 5e (2014) checks to the LLM tool runtime."""

from __future__ import annotations

from collections.abc import Mapping
import re
from typing import Any

from src.chat.actions import ActionContext
from src.chat.tools import (
    ToolDefinition,
    ToolExecutionContext,
    ToolOutcome,
    ToolRegistry,
)

from .action import Dnd5eCheckAction, Dnd5eCheckRequest
from .engine import D20RollMode, Dnd5eCheckError, Dnd5eEngine

_DND5E_RULE_PATTERN = re.compile(
    r"(?:d\s*&\s*d|dnd|龙与地下城)\s*"
    r"(?:5\s*e|第五版|2014(?:\s*版)?)"
    r"|(?:5\s*e|第五版|2014(?:\s*版)?).{0,8}"
    r"(?:d\s*&\s*d|dnd|龙与地下城)",
    re.IGNORECASE,
)

_DND5E_CHECK_PATTERN = re.compile(
    r"检定|攻击|豁免|优势|劣势",
    re.IGNORECASE,
)

_DND5E_REQUEST_PATTERN = re.compile(
    r"帮|请|给我|来(?:个|一次|一下)?|进行|做(?:个|一次|一下)?|"
    r"掷|骰|roll",
    re.IGNORECASE,
)

_DISCUSSION_PATTERN = re.compile(
    r"怎么|如何|为什么|什么是|啥是|区别|规则|解释|介绍|"
    r"机制|概率|多少|是否",
)


def message_requests_dnd5e_check(text: str) -> bool:
    """Return whether this message explicitly requests a DND 5e (2014) check."""

    normalized = text.strip()
    if not normalized:
        return False

    if not _DND5E_RULE_PATTERN.search(normalized):
        return False

    if not _DND5E_CHECK_PATTERN.search(normalized):
        return False

    if _DND5E_REQUEST_PATTERN.search(normalized):
        return True

    return (
        len(normalized) <= 32
        and not _DISCUSSION_PATTERN.search(normalized)
    )


def create_dnd5e_check_tool(
    engine: Dnd5eEngine | None = None,
    *,
    action: Dnd5eCheckAction | None = None,
) -> ToolDefinition:
    check_action = action or Dnd5eCheckAction(engine or Dnd5eEngine())

    async def dnd5e_check(
        arguments: Mapping[str, Any],
        context: ToolExecutionContext,
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

        result = await check_action.execute(
            Dnd5eCheckRequest(modifier=modifier, mode=mode),
            ActionContext(
                user_id=context.user_id,
                user_name=context.user_name,
                platform=context.platform,
            ),
        )
        return ToolOutcome(
            data=result.data,
            authoritative_output=result.authoritative_output,
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
        availability=lambda context: (
            context.user_text is None
            or message_requests_dnd5e_check(context.user_text)
        ),
    )


def register_dnd5e_tools(
    registry: ToolRegistry,
    engine: Dnd5eEngine | None = None,
    *,
    action: Dnd5eCheckAction | None = None,
) -> None:
    registry.register(create_dnd5e_check_tool(engine, action=action))
