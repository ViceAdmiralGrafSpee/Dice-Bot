from __future__ import annotations

import pytest

from src.chat.actions import ActionContext, ActionResult
from src.chat.tools import (
    PortableToolService,
    ToolRegistry,
    register_character_management_tools,
)


@pytest.mark.asyncio
async def test_character_list_tool_uses_shared_action_and_caller_identity() -> None:
    calls: list[ActionContext] = []

    class RecordingAction:
        async def execute(self, _request, context):
            calls.append(context)
            return ActionResult(
                data={
                    "characters": [
                        {
                            "character_id": "character-1",
                            "name": "阿莉娅",
                            "ruleset": "dnd5r",
                            "status": "active",
                        }
                    ]
                },
                authoritative_output=(
                    "你的角色卡：\n- 阿莉娅｜dnd5r｜ID：character-1"
                ),
            )

    registry = ToolRegistry()
    register_character_management_tools(
        registry,
        list_action=RecordingAction(),
    )
    service = PortableToolService(registry)

    payload = await service.execute_tool_call(
        {"name": "character_list", "arguments": {}},
        user_id="10001",
        user_name="玩家甲",
        platform="qq",
        message_text="帮我看看我的角色卡列表",
    )

    assert payload == {
        "ok": True,
        "tool": "character_list",
        "result": {
            "characters": [
                {
                    "character_id": "character-1",
                    "name": "阿莉娅",
                    "ruleset": "dnd5r",
                    "status": "active",
                }
            ]
        },
        "authoritative_output": (
            "你的角色卡：\n- 阿莉娅｜dnd5r｜ID：character-1"
        ),
    }
    assert calls == [
        ActionContext(
            user_id="10001",
            user_name="玩家甲",
            platform="qq",
        )
    ]


@pytest.mark.asyncio
async def test_character_list_tool_rejects_invented_arguments() -> None:
    class UnusedAction:
        async def execute(self, _request, _context):
            raise AssertionError("带参数的请求不应进入 Action")

    registry = ToolRegistry()
    register_character_management_tools(
        registry,
        list_action=UnusedAction(),
    )
    service = PortableToolService(registry)

    payload = await service.execute_tool_call(
        {
            "name": "character_list",
            "arguments": {"user_id": "someone-else"},
        },
        user_id="10001",
        platform="qq",
    )

    assert payload == {"error": "character_list 不接收参数"}
