"""Platform-neutral Actions for saving, previewing, and confirming drafts."""

from __future__ import annotations

from dataclasses import dataclass

from src.trpg.importing import CharacterDraft, ValidationSeverity
from src.trpg.importing.service import CharacterDraftService

from .runtime import ActionContext, ActionResult


@dataclass(frozen=True, slots=True)
class SaveCharacterDraftRequest:
    draft: CharacterDraft
    draft_id: str | None = None


@dataclass(frozen=True, slots=True)
class PreviewCharacterDraftRequest:
    draft_id: str


@dataclass(frozen=True, slots=True)
class ConfirmCharacterDraftRequest:
    draft_id: str
    confirmation_text: str
    character_id: str | None = None


@dataclass(slots=True)
class SaveCharacterDraftAction:
    service: CharacterDraftService

    async def execute(
        self,
        request: SaveCharacterDraftRequest,
        context: ActionContext,
    ) -> ActionResult:
        platform, user_id, user_name = _require_identity(context)
        record = await self.service.save(
            request.draft,
            owner_platform=platform,
            owner_user_id=user_id,
            owner_name=user_name,
            draft_id=request.draft_id,
        )
        _, preview = await self.service.preview(
            record.draft_id,
            owner_platform=platform,
            owner_user_id=user_id,
        )
        return ActionResult(
            data={
                "draft_id": record.draft_id,
                "ruleset": record.draft.ruleset_key,
                "status": record.status.value,
                "errors": _issue_count(record.draft, ValidationSeverity.ERROR),
                "warnings": _issue_count(
                    record.draft, ValidationSeverity.WARNING
                ),
            },
            authoritative_output=preview,
        )


@dataclass(slots=True)
class PreviewCharacterDraftAction:
    service: CharacterDraftService

    async def execute(
        self,
        request: PreviewCharacterDraftRequest,
        context: ActionContext,
    ) -> ActionResult:
        platform, user_id, _ = _require_identity(context)
        record, preview = await self.service.preview(
            request.draft_id,
            owner_platform=platform,
            owner_user_id=user_id,
        )
        return ActionResult(
            data={
                "draft_id": record.draft_id,
                "status": record.status.value,
                "confirmed_character_id": record.confirmed_character_id,
            },
            authoritative_output=preview,
        )


@dataclass(slots=True)
class ConfirmCharacterDraftAction:
    service: CharacterDraftService

    async def execute(
        self,
        request: ConfirmCharacterDraftRequest,
        context: ActionContext,
    ) -> ActionResult:
        platform, user_id, _ = _require_identity(context)
        expected_confirmation = f"确认 {request.draft_id.strip()}"
        if request.confirmation_text.strip() != expected_confirmation:
            raise ValueError(
                f"确认口令不匹配；请明确发送：{expected_confirmation}"
            )
        character = await self.service.confirm(
            request.draft_id,
            owner_platform=platform,
            owner_user_id=user_id,
            character_id=request.character_id,
        )
        return ActionResult(
            data={
                "draft_id": request.draft_id,
                "character_id": character.character_id,
                "ruleset": character.ruleset_key,
                "name": character.name,
                "sheet_version": character.sheet_version,
            },
            authoritative_output=(
                f"已确认并导入 {character.ruleset_key} 角色卡：{character.name}"
                f"（ID：{character.character_id}）"
            ),
        )


def _require_identity(context: ActionContext) -> tuple[str, str, str]:
    if not context.platform or not context.user_id:
        raise ValueError("角色草稿操作需要明确的平台和用户身份")
    return (
        context.platform,
        context.user_id,
        context.user_name or context.user_id,
    )


def _issue_count(
    draft: CharacterDraft,
    severity: ValidationSeverity,
) -> int:
    return sum(issue.severity is severity for issue in draft.validation)


__all__ = [
    "ConfirmCharacterDraftAction",
    "ConfirmCharacterDraftRequest",
    "PreviewCharacterDraftAction",
    "PreviewCharacterDraftRequest",
    "SaveCharacterDraftAction",
    "SaveCharacterDraftRequest",
]
