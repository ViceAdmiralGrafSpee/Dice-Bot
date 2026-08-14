"""Platform-neutral Actions for listing and safely archiving characters."""

from __future__ import annotations

from dataclasses import dataclass

from src.trpg.characters import CharacterManagementService

from .runtime import ActionContext, ActionResult


@dataclass(frozen=True, slots=True)
class ListOwnedCharactersRequest:
    pass


@dataclass(frozen=True, slots=True)
class PrepareArchiveCharacterRequest:
    character_id: str


@dataclass(frozen=True, slots=True)
class ConfirmArchiveCharacterRequest:
    character_id: str
    confirmation_text: str


@dataclass(slots=True)
class ListOwnedCharactersAction:
    service: CharacterManagementService

    async def execute(
        self,
        request: ListOwnedCharactersRequest,
        context: ActionContext,
    ) -> ActionResult:
        del request
        platform, user_id = _require_identity(context)
        characters = await self.service.list_owned(
            owner_platform=platform,
            owner_user_id=user_id,
        )
        if not characters:
            output = "你还没有已导入的角色卡。"
        else:
            lines = ["你的角色卡："]
            lines.extend(
                f"- {character.name}｜{character.ruleset_key}｜ID：{character.character_id}"
                for character in characters
            )
            output = "\n".join(lines)
        return ActionResult(
            data={
                "characters": [
                    {
                        "character_id": character.character_id,
                        "name": character.name,
                        "ruleset": character.ruleset_key,
                        "status": character.status,
                    }
                    for character in characters
                ]
            },
            authoritative_output=output,
        )


@dataclass(slots=True)
class PrepareArchiveCharacterAction:
    service: CharacterManagementService

    async def execute(
        self,
        request: PrepareArchiveCharacterRequest,
        context: ActionContext,
    ) -> ActionResult:
        platform, user_id = _require_identity(context)
        character = await self.service.get_owned(
            request.character_id,
            owner_platform=platform,
            owner_user_id=user_id,
        )
        if character.status == "archived":
            raise ValueError(
                f"角色卡已经删除（可恢复）：{character.name}（ID：{character.character_id}）"
            )
        confirmation = f"确认删除 {character.character_id}"
        return ActionResult(
            data={
                "character_id": character.character_id,
                "name": character.name,
                "ruleset": character.ruleset_key,
                "confirmation": confirmation,
            },
            authoritative_output=(
                f"准备删除角色卡：{character.name}\n"
                f"规则：{character.ruleset_key}\n"
                f"ID：{character.character_id}\n\n"
                "这会把角色卡归档；导入来源和参团历史仍会保留，未来可以恢复。\n"
                f"若确定，请完整发送：{confirmation}"
            ),
        )


@dataclass(slots=True)
class ConfirmArchiveCharacterAction:
    service: CharacterManagementService

    async def execute(
        self,
        request: ConfirmArchiveCharacterRequest,
        context: ActionContext,
    ) -> ActionResult:
        character_id = request.character_id.strip()
        expected_confirmation = f"确认删除 {character_id}"
        if request.confirmation_text.strip() != expected_confirmation:
            raise ValueError(
                f"确认口令不匹配；请明确发送：{expected_confirmation}"
            )
        platform, user_id = _require_identity(context)
        character = await self.service.archive_owned(
            character_id,
            owner_platform=platform,
            owner_user_id=user_id,
        )
        return ActionResult(
            data={
                "character_id": character.character_id,
                "name": character.name,
                "ruleset": character.ruleset_key,
                "status": character.status,
            },
            authoritative_output=(
                f"角色卡已删除（可恢复）：{character.name}"
                f"（ID：{character.character_id}）"
            ),
        )


def _require_identity(context: ActionContext) -> tuple[str, str]:
    if not context.platform or not context.user_id:
        raise ValueError("角色卡操作需要明确的平台和用户身份")
    return context.platform, context.user_id


__all__ = [
    "ConfirmArchiveCharacterAction",
    "ConfirmArchiveCharacterRequest",
    "ListOwnedCharactersAction",
    "ListOwnedCharactersRequest",
    "PrepareArchiveCharacterAction",
    "PrepareArchiveCharacterRequest",
]
