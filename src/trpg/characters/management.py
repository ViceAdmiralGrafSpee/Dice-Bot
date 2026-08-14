"""Rule-neutral character ownership and lifecycle service."""

from __future__ import annotations

from dataclasses import dataclass

from src.trpg.models import Character
from src.trpg.repository import SQLiteTrpgRepository


class CharacterNotFoundError(LookupError):
    """Raised when a character does not exist or is not owned by the caller."""


class CharacterArchivedError(ValueError):
    """Raised when an operation requires an active character."""


@dataclass(slots=True)
class CharacterManagementService:
    repository: SQLiteTrpgRepository

    async def list_owned(
        self,
        *,
        owner_platform: str,
        owner_user_id: str,
    ) -> list[Character]:
        return await self.repository.list_characters_for_owner(
            owner_platform=owner_platform,
            owner_user_id=owner_user_id,
            status="active",
        )

    async def get_owned(
        self,
        character_id: str,
        *,
        owner_platform: str,
        owner_user_id: str,
    ) -> Character:
        character = await self.repository.get_character(character_id.strip())
        if (
            character is None
            or character.owner_platform != owner_platform.strip().lower()
            or character.owner_user_id != owner_user_id.strip()
        ):
            raise CharacterNotFoundError(
                f"找不到属于你的角色卡：{character_id}"
            )
        return character

    async def archive_owned(
        self,
        character_id: str,
        *,
        owner_platform: str,
        owner_user_id: str,
    ) -> Character:
        character = await self.get_owned(
            character_id,
            owner_platform=owner_platform,
            owner_user_id=owner_user_id,
        )
        if character.status == "archived":
            raise CharacterArchivedError(
                f"角色卡已经删除（可恢复）：{character.name}（ID：{character.character_id}）"
            )
        archived = await self.repository.archive_character_for_owner(
            character_id=character.character_id,
            owner_platform=owner_platform,
            owner_user_id=owner_user_id,
        )
        if archived is None:
            raise CharacterNotFoundError(
                f"找不到属于你的角色卡：{character_id}"
            )
        return archived


__all__ = [
    "CharacterArchivedError",
    "CharacterManagementService",
    "CharacterNotFoundError",
]
