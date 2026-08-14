"""D&D 5e (2014) character import validation and persistence."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.trpg import Character, SQLiteTrpgRepository
from src.trpg.characters import CharacterImportData


DND5E_CHARACTER_SHEET_VERSION = 1
DICE_BOT_JSON_V1 = "dice_bot_json_v1"


@dataclass(slots=True)
class Dnd5eCharacterService:
    repository: SQLiteTrpgRepository
    ruleset_key: str = "dnd5e"

    async def import_character(self, request: CharacterImportData) -> Character:
        source_format = request.source_format.strip().lower()
        if source_format != DICE_BOT_JSON_V1:
            raise ValueError(f"DND5e 暂不支持该角色卡格式：{source_format}")

        sheet = _validate_and_normalize_sheet(request.sheet_data)
        return await self.repository.create_character(
            character_id=request.character_id,
            owner_platform=request.owner_platform,
            owner_user_id=request.owner_user_id,
            owner_name=request.owner_name,
            name=sheet["name"],
            ruleset_key=self.ruleset_key,
            sheet_version=DND5E_CHARACTER_SHEET_VERSION,
            sheet_data=sheet,
        )


def _validate_and_normalize_sheet(sheet_data: Any) -> dict[str, Any]:
    if not isinstance(sheet_data, dict):
        try:
            sheet = dict(sheet_data)
        except (TypeError, ValueError) as error:
            raise ValueError("DND5e 角色卡必须是结构化对象") from error
    else:
        sheet = dict(sheet_data)

    name = sheet.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ValueError("DND5e 角色卡缺少有效的 name")
    sheet["name"] = name.strip()

    edition = str(sheet.get("edition", "2014")).strip().lower()
    if edition not in {"2014", "5e-2014", "5e 2014"}:
        raise ValueError("当前 dnd5e 服务只接受 D&D 5e 2014 角色卡")
    sheet["edition"] = "2014"

    if "level" in sheet:
        level = sheet["level"]
        if (
            isinstance(level, bool)
            or not isinstance(level, int)
            or not 1 <= level <= 20
        ):
            raise ValueError("DND5e 角色等级 level 必须是 1 到 20 的整数")

    return sheet
