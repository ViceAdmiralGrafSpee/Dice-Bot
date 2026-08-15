"""Platform-independent registration boundary for tabletop rule systems."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from src.chat.commands import CommandRegistry
from src.chat.tools import ToolRegistry


class RuleSystem(Protocol):
    """A rule plugin that can expose traditional commands."""

    system_id: str
    display_name: str

    def register_commands(self, registry: CommandRegistry) -> None: ...

    def register_tools(self, registry: ToolRegistry) -> None: ...


@dataclass(slots=True)
class RuleSystemRegistry:
    """Keep rule editions separate and install their commands explicitly."""

    _systems: dict[str, RuleSystem] = field(default_factory=dict)

    def register(self, system: RuleSystem) -> None:
        system_id = self._normalize_id(system.system_id)
        if system_id in self._systems:
            raise ValueError(f"规则系统已注册：{system_id}")
        self._systems[system_id] = system

    def get(self, system_id: str) -> RuleSystem | None:
        return self._systems.get(self._normalize_id(system_id))

    def register_commands(self, registry: CommandRegistry) -> None:
        for system in self._systems.values():
            system.register_commands(registry)

    def register_tools(self, registry: ToolRegistry) -> None:
        for system in self._systems.values():
            system.register_tools(registry)

    @staticmethod
    def _normalize_id(system_id: str) -> str:
        normalized = system_id.strip().lower()
        if not normalized or any(character.isspace() for character in normalized):
            raise ValueError("规则系统标识不能为空或包含空白")
        return normalized
