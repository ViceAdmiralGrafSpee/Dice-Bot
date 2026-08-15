"""Durable preview-and-confirm workflow for character import drafts."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Mapping

from src.trpg.characters import CharacterImportData, CharacterServiceRegistry
from src.trpg.models import Character
from src.trpg.repository import SQLiteTrpgRepository
from src.trpg.schemas import CharacterSchema

from .models import (
    CharacterDraft,
    CharacterDraftStatus,
    StoredCharacterDraft,
    ValidationSeverity,
)
from .serialization import draft_confirmation_payload


CHARACTER_DRAFT_V1 = "character_draft_v1"


class CharacterDraftNotFoundError(LookupError):
    pass


class CharacterDraftOwnershipError(PermissionError):
    pass


class CharacterDraftValidationError(ValueError):
    pass


@dataclass(slots=True)
class CharacterDraftService:
    repository: SQLiteTrpgRepository
    character_services: CharacterServiceRegistry
    schemas: Mapping[str, CharacterSchema]

    async def save(
        self,
        draft: CharacterDraft,
        *,
        owner_platform: str,
        owner_user_id: str,
        owner_name: str,
        draft_id: str | None = None,
    ) -> StoredCharacterDraft:
        ruleset_key = draft.ruleset_key.strip().lower()
        if ruleset_key not in self.schemas:
            raise ValueError(f"没有可预览的角色 Schema：{ruleset_key}")
        return await self.repository.save_character_draft(
            draft=draft,
            owner_platform=owner_platform,
            owner_user_id=owner_user_id,
            owner_name=owner_name,
            draft_id=draft_id,
        )

    async def get_owned(
        self,
        draft_id: str,
        *,
        owner_platform: str,
        owner_user_id: str,
    ) -> StoredCharacterDraft:
        record = await self.repository.get_character_draft(draft_id.strip())
        if record is None:
            raise CharacterDraftNotFoundError(f"找不到角色导入草稿：{draft_id}")
        if (
            record.owner_platform != owner_platform.strip().lower()
            or record.owner_user_id != owner_user_id.strip()
        ):
            raise CharacterDraftOwnershipError("不能查看或确认其他用户的草稿")
        return record

    async def preview(
        self,
        draft_id: str,
        *,
        owner_platform: str,
        owner_user_id: str,
    ) -> tuple[StoredCharacterDraft, str]:
        record = await self.get_owned(
            draft_id,
            owner_platform=owner_platform,
            owner_user_id=owner_user_id,
        )
        schema = self.schemas.get(record.draft.ruleset_key.strip().lower())
        return record, render_character_draft_preview(record, schema)

    async def confirm(
        self,
        draft_id: str,
        *,
        owner_platform: str,
        owner_user_id: str,
        character_id: str | None = None,
    ) -> Character:
        record = await self.get_owned(
            draft_id,
            owner_platform=owner_platform,
            owner_user_id=owner_user_id,
        )
        if record.status is CharacterDraftStatus.CONFIRMED:
            if record.confirmed_character_id is None:
                raise RuntimeError("已确认草稿缺少关联角色 ID")
            character = await self.repository.get_character(
                record.confirmed_character_id
            )
            if character is None:
                raise RuntimeError("已确认草稿关联的角色不存在")
            return character
        if record.draft.has_errors:
            error_count = sum(
                issue.severity is ValidationSeverity.ERROR
                for issue in record.draft.validation
            )
            raise CharacterDraftValidationError(
                f"草稿还有 {error_count} 个 ERROR，修正或人工确认字段后才能导入"
            )

        return await self.character_services.import_character(
            record.draft.ruleset_key,
            CharacterImportData(
                owner_platform=record.owner_platform,
                owner_user_id=record.owner_user_id,
                owner_name=record.owner_name,
                sheet_data=draft_confirmation_payload(record.draft),
                source_format=CHARACTER_DRAFT_V1,
                character_id=character_id,
                source_draft_id=record.draft_id,
            ),
        )


def render_character_draft_preview(
    record: StoredCharacterDraft,
    schema: CharacterSchema | None,
) -> str:
    draft = record.draft
    labels = {
        definition.path: (
            definition.aliases[0] if definition.aliases else definition.path
        )
        for definition in schema.fields
    } if schema is not None else {}
    ordered_paths = (
        [definition.path for definition in schema.fields]
        if schema is not None
        else list(draft.fields)
    )
    lines = [
        f"角色卡导入草稿：{record.draft_id}",
        f"规则：{draft.ruleset_key}（Schema v{draft.schema_version}）",
        f"来源：{draft.source.original_filename}",
        f"模板：{draft.template_profile_id or '未知模板'}",
        "",
        "识别结果：",
    ]
    for path in ordered_paths:
        field = draft.fields.get(path)
        if field is None:
            continue
        lines.append(f"- {labels.get(path, path)}：{_display_value(field.value)}")

    errors = [
        issue
        for issue in draft.validation
        if issue.severity is ValidationSeverity.ERROR
    ]
    warnings = [
        issue
        for issue in draft.validation
        if issue.severity is ValidationSeverity.WARNING
    ]
    lines.extend(
        (
            "",
            f"检查结果：{len(errors)} 个 ERROR，{len(warnings)} 个 WARNING",
        )
    )
    for issue in (*errors, *warnings)[:8]:
        lines.append(f"- [{issue.severity.value.upper()}] {issue.message}")
    remaining_issues = len(errors) + len(warnings) - 8
    if remaining_issues > 0:
        lines.append(f"- 另有 {remaining_issues} 条检查信息未展开")
    lines.append(f"未映射来源区域：{len(draft.unmapped_regions)} 个（已保留）")

    if record.status is CharacterDraftStatus.CONFIRMED:
        lines.extend(
            (
                "",
                f"状态：已确认，角色 ID：{record.confirmed_character_id}",
            )
        )
    elif errors:
        lines.extend(("", "状态：待修正；存在 ERROR，当前禁止确认。"))
    else:
        lines.extend(
            (
                "",
                "状态：等待用户明确确认；确认前不会写入正式角色库。",
                f"若结果无误，请明确发送：确认 {record.draft_id}",
            )
        )
    return "\n".join(lines)


def _display_value(value: object) -> str:
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return str(value)


__all__ = [
    "CHARACTER_DRAFT_V1",
    "CharacterDraftNotFoundError",
    "CharacterDraftOwnershipError",
    "CharacterDraftService",
    "CharacterDraftValidationError",
    "render_character_draft_preview",
]
