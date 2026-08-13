"""D&D 5e (2014) rule-system plugin."""

from __future__ import annotations

from dataclasses import dataclass

from src.chat.commands import CommandRegistry
from src.chat.tools import ToolRegistry

from .commands import register_dnd5e_commands
from .engine import Dnd5eEngine
from .tool import register_dnd5e_tools


@dataclass(frozen=True, slots=True)
class Dnd5eRuleSystem:
    system_id: str = "dnd5e"
    display_name: str = "Dungeons & Dragons 5e (2014)"
    engine: Dnd5eEngine | None = None

    def register_commands(self, registry: CommandRegistry) -> None:
        register_dnd5e_commands(registry, self.engine)

    def register_tools(self, registry: ToolRegistry) -> None:
        register_dnd5e_tools(registry, self.engine)
