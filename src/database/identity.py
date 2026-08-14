"""Stable platform-scoped identities for PostgreSQL-backed user data."""

from __future__ import annotations

from dataclasses import dataclass
import re


_PLATFORM_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,15}$")
_MAX_DATABASE_ID_LENGTH = 50


@dataclass(frozen=True, slots=True)
class PlatformUserIdentity:
    """A platform SDK-independent user identity.

    Existing Discord rows historically stored the raw numeric ID, so Discord
    keeps that representation for compatibility. Every other platform is
    namespaced, which prevents a QQ number colliding with a Discord snowflake.
    """

    platform: str
    user_id: str

    def __post_init__(self) -> None:
        platform = self.platform.strip().lower()
        user_id = self.user_id.strip()
        if not _PLATFORM_PATTERN.fullmatch(platform):
            raise ValueError(f"invalid platform name: {self.platform!r}")
        if not user_id:
            raise ValueError("user_id cannot be empty")
        object.__setattr__(self, "platform", platform)
        object.__setattr__(self, "user_id", user_id)
        if len(self.database_key) > _MAX_DATABASE_ID_LENGTH:
            raise ValueError("platform-scoped user ID exceeds 50 characters")

    @property
    def database_key(self) -> str:
        if self.platform == "discord":
            return self.user_id
        return f"{self.platform}:{self.user_id}"

    @property
    def external_id(self) -> str:
        return f"platform:{self.platform}:{self.user_id}"


def platform_user_identity(platform: str, user_id: str | int) -> PlatformUserIdentity:
    return PlatformUserIdentity(platform=platform, user_id=str(user_id))
