"""Platform-neutral boundary for rule-specific character services."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

from src.trpg.models import Character


@dataclass(frozen=True, slots=True)
class CharacterImportData:
    owner_platform: str
    owner_user_id: str
    owner_name: str
    sheet_data: Mapping[str, Any]
    source_format: str = "dice_bot_json_v1"
    character_id: str | None = None
    source_draft_id: str | None = None


class CharacterService(Protocol):
    """One ruleset's authoritative character operations."""

    ruleset_key: str

    async def import_character(self, request: CharacterImportData) -> Character: ...


class CharacterServiceNotFoundError(LookupError):
    """Raised when no character service owns the requested ruleset."""


@dataclass(slots=True)
class CharacterServiceRegistry:
    """Choose the correct service before any character data is written."""

    _services: dict[str, CharacterService] = field(default_factory=dict)

    def register(self, service: CharacterService) -> None:
        ruleset_key = self._normalize_ruleset_key(service.ruleset_key)
        if ruleset_key in self._services:
            raise ValueError(f"角色服务已注册：{ruleset_key}")
        self._services[ruleset_key] = service

    def get(self, ruleset_key: str) -> CharacterService | None:
        return self._services.get(self._normalize_ruleset_key(ruleset_key))

    async def import_character(
        self,
        ruleset_key: str,
        request: CharacterImportData,
    ) -> Character:
        normalized_key = self._normalize_ruleset_key(ruleset_key)
        service = self._services.get(normalized_key)
        if service is None:
            raise CharacterServiceNotFoundError(
                f"尚未支持该角色规则系统：{normalized_key}"
            )
        return await service.import_character(request)

    @staticmethod
    def _normalize_ruleset_key(ruleset_key: str) -> str:
        normalized = ruleset_key.strip().lower()
        if not normalized or any(character.isspace() for character in normalized):
            raise ValueError("角色规则系统标识不能为空或包含空白")
        return normalized
