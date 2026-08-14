"""Create the minimal PostgreSQL profile needed by long-term memory."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from src.database.database import AsyncSessionLocal
from src.database.identity import PlatformUserIdentity
from src.database.models import CommunityMemberProfile


class MemberProfileService:
    """Platform-neutral profile bootstrap service.

    It only fills the minimum fields required by the existing schema. A later
    community import can enrich the same row without depending on this service.
    """

    @staticmethod
    def minimal_values(
        identity: PlatformUserIdentity, display_name: str
    ) -> dict[str, Any]:
        safe_name = display_name.strip() or identity.user_id
        return {
            "external_id": identity.external_id,
            "user_id": identity.database_key,
            "title": safe_name,
            "full_text": (
                "自动建立的平台用户档案\n"
                f"平台: {identity.platform}\n"
                f"显示名: {safe_name}"
            ),
            "source_metadata": {
                "platform": identity.platform,
                "platform_user_id": identity.user_id,
                "display_name": safe_name,
                "auto_created": True,
            },
            "history": [],
        }

    async def ensure_minimal_profile(
        self, identity: PlatformUserIdentity, display_name: str
    ) -> CommunityMemberProfile:
        values = self.minimal_values(identity, display_name)
        async with AsyncSessionLocal() as session:
            statement = (
                insert(CommunityMemberProfile)
                .values(**values)
                .on_conflict_do_nothing(index_elements=["user_id"])
            )
            await session.execute(statement)
            await session.commit()

            result = await session.execute(
                select(CommunityMemberProfile).where(
                    CommunityMemberProfile.user_id == identity.database_key
                )
            )
            profile = result.scalars().first()
            if profile is None:
                raise RuntimeError(
                    f"failed to create or load profile for {identity.database_key}"
                )
            return profile


member_profile_service = MemberProfileService()
