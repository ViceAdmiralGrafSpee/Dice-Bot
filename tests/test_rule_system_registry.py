from dataclasses import dataclass

import pytest

from src.chat.commands import CommandRegistry, CommandRequest, CommandResult
from src.chat.rules import RuleSystemRegistry
from src.chat.tools import ToolDefinition, ToolOutcome, ToolRegistry


@dataclass(frozen=True)
class FakeRuleSystem:
    system_id: str
    display_name: str = "Fake rules"

    def register_commands(self, registry: CommandRegistry) -> None:
        registry.register(
            self.system_id,
            lambda _request: CommandResult(self.system_id),
        )

    def register_tools(self, registry: ToolRegistry) -> None:
        async def handler(_arguments, _context):
            return ToolOutcome(data={"system_id": self.system_id})

        registry.register(
            ToolDefinition(
                name=f"{self.system_id}_tool",
                description="Fake tool",
                parameters={"type": "object", "properties": {}},
                handler=handler,
            )
        )


def test_registers_rule_system_and_installs_its_commands() -> None:
    systems = RuleSystemRegistry()
    system = FakeRuleSystem("example")
    systems.register(system)
    commands = CommandRegistry()

    systems.register_commands(commands)
    tools = ToolRegistry()
    systems.register_tools(tools)

    assert systems.get("EXAMPLE") is system
    assert commands.dispatch(".example") == CommandResult("example")
    assert tools.get("example_tool") is not None


def test_rejects_duplicate_rule_system_id() -> None:
    systems = RuleSystemRegistry()
    systems.register(FakeRuleSystem("example"))

    with pytest.raises(ValueError, match="规则系统已注册"):
        systems.register(FakeRuleSystem("EXAMPLE"))
