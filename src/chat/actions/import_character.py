"""Shared Action that routes a character import to its ruleset service."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from src.trpg.characters import CharacterImportData, CharacterServiceRegistry

from .runtime import ActionContext, ActionResult


@dataclass(frozen=True, slots=True)
class ImportCharacterRequest:
    ruleset_key: str
    sheet_data: Mapping[str, Any]
    source_format: str = "dice_bot_json_v1"
    character_id: str | None = None


@dataclass(slots=True)
class ImportCharacterAction:
    services: CharacterServiceRegistry

    async def execute(
        self,
        request: ImportCharacterRequest,
        context: ActionContext,
    ) -> ActionResult:
        if not context.platform or not context.user_id:
            raise ValueError("导入角色卡需要明确的平台和用户身份")
        character = await self.services.import_character(
            request.ruleset_key,
            CharacterImportData(
                owner_platform=context.platform,
                owner_user_id=context.user_id,
                owner_name=context.user_name or context.user_id,
                sheet_data=request.sheet_data,
                source_format=request.source_format,
                character_id=request.character_id,
            ),
        )
        return ActionResult(
            data={
                "character_id": character.character_id,
                "ruleset": character.ruleset_key,
                "name": character.name,
                "sheet_version": character.sheet_version,
            },
            authoritative_output=(
                f"已导入 {character.ruleset_key} 角色卡：{character.name}"
                f"（ID：{character.character_id}）"
            ),
        )
