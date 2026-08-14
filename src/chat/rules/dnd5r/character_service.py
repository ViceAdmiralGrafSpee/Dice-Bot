"""D&D 5r confirmation validation and formal Character persistence."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.trpg import Character, SQLiteTrpgRepository
from src.trpg.characters import CharacterImportData
from src.trpg.importing.service import CHARACTER_DRAFT_V1

from .character_schema import DND5R_CHARACTER_SCHEMA


DND5R_CHARACTER_SHEET_VERSION = 1


@dataclass(slots=True)
class Dnd5rCharacterService:
    repository: SQLiteTrpgRepository
    ruleset_key: str = "dnd5r"

    async def import_character(self, request: CharacterImportData) -> Character:
        source_format = request.source_format.strip().lower()
        if source_format != CHARACTER_DRAFT_V1:
            raise ValueError(
                "DND5r 当前只接受经过用户确认的 CharacterDraft"
            )
        if not request.source_draft_id:
            raise ValueError("DND5r 草稿确认缺少 source_draft_id")

        sheet = _validate_and_normalize_draft_payload(request.sheet_data)
        sheet["import_provenance"]["draft_id"] = request.source_draft_id
        return await self.repository.create_character_from_draft(
            draft_id=request.source_draft_id,
            character_id=request.character_id,
            owner_platform=request.owner_platform,
            owner_user_id=request.owner_user_id,
            owner_name=request.owner_name,
            name=sheet["identity"]["name"],
            ruleset_key=self.ruleset_key,
            sheet_version=DND5R_CHARACTER_SHEET_VERSION,
            sheet_data=sheet,
        )


def _validate_and_normalize_draft_payload(
    sheet_data: Any,
) -> dict[str, Any]:
    try:
        payload = dict(sheet_data)
    except (TypeError, ValueError) as error:
        raise ValueError("DND5r 草稿确认数据必须是结构化对象") from error
    if str(payload.get("ruleset_key", "")).strip().lower() != "dnd5r":
        raise ValueError("DND5r 草稿的规则系统标识不正确")
    if payload.get("schema_version") != DND5R_CHARACTER_SCHEMA.version:
        raise ValueError("DND5r 草稿 Schema 版本不受支持")

    fields = payload.get("fields")
    if not isinstance(fields, dict):
        raise ValueError("DND5r 草稿缺少 fields 对象")
    definitions = {
        definition.path: definition
        for definition in DND5R_CHARACTER_SCHEMA.fields
    }
    unknown_paths = set(fields) - set(definitions)
    if unknown_paths:
        raise ValueError(
            "DND5r 草稿含未声明的标准字段："
            + ", ".join(sorted(str(path) for path in unknown_paths))
        )

    normalized: dict[str, Any] = {
        "edition": "2024",
        "schema_version": DND5R_CHARACTER_SCHEMA.version,
    }
    for path, definition in definitions.items():
        if path not in fields:
            if definition.required:
                raise ValueError(f"DND5r 草稿缺少必填字段：{path}")
            continue
        value = fields[path]
        if definition.value_type == "integer" and (
            isinstance(value, bool) or not isinstance(value, int)
        ):
            raise ValueError(f"DND5r 字段 {path} 必须是整数")
        if definition.value_type == "string" and (
            not isinstance(value, str) or not value.strip()
        ):
            raise ValueError(f"DND5r 字段 {path} 必须是非空文字")
        _set_dotted_value(normalized, path, value.strip() if isinstance(value, str) else value)

    extensions = payload.get("extensions", {})
    if not isinstance(extensions, dict):
        raise ValueError("DND5r 草稿 extensions 必须是对象")
    source = payload.get("source", {})
    provenance = payload.get("field_provenance", {})
    if not isinstance(source, dict) or not isinstance(provenance, dict):
        raise ValueError("DND5r 草稿来源信息格式不正确")
    normalized["extensions"] = dict(extensions)
    normalized["import_provenance"] = {
        "source": dict(source),
        "template_profile_id": payload.get("template_profile_id"),
        "fields": dict(provenance),
    }
    return normalized


def _set_dotted_value(target: dict[str, Any], path: str, value: Any) -> None:
    parts = path.split(".")
    current = target
    for part in parts[:-1]:
        child = current.setdefault(part, {})
        if not isinstance(child, dict):
            raise ValueError(f"DND5r 字段路径冲突：{path}")
        current = child
    current[parts[-1]] = value


__all__ = ["DND5R_CHARACTER_SHEET_VERSION", "Dnd5rCharacterService"]
