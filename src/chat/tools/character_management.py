"""Expose read-only character management Actions to the LLM tool runtime."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from src.chat.actions import (
    ActionContext,
    ListOwnedCharactersAction,
    ListOwnedCharactersRequest,
)

from .runtime import (
    ToolDefinition,
    ToolExecutionContext,
    ToolOutcome,
    ToolRegistry,
)


def create_character_list_tool(
    action: ListOwnedCharactersAction,
) -> ToolDefinition:
    """Create the read-only tool backed by the traditional command Action."""

    async def character_list(
        arguments: Mapping[str, Any],
        context: ToolExecutionContext,
    ) -> ToolOutcome:
        if arguments:
            raise ValueError("character_list 不接收参数")

        result = await action.execute(
            ListOwnedCharactersRequest(),
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
        name="character_list",
        description=(
            "查询当前用户已经导入且尚未归档的角色卡列表。仅当用户要求查看、"
            "列出或查询自己的角色卡、PC、人物卡时调用；这是只读查询，不会修改"
            "任何角色数据。不得使用掷骰或检定工具代替本工具，也不得用本工具执行"
            "检定、随机数或规则结算。"
        ),
        parameters={
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
        handler=character_list,
        category="character",
    )


def register_character_management_tools(
    registry: ToolRegistry,
    *,
    list_action: ListOwnedCharactersAction,
) -> None:
    registry.register(create_character_list_tool(list_action))


__all__ = [
    "create_character_list_tool",
    "register_character_management_tools",
]
