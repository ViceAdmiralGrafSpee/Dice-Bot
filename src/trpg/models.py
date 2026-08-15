"""Small rule-neutral data models for campaigns and characters."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class Campaign:
    campaign_id: str
    name: str
    ruleset_key: str
    platform: str
    conversation_id: str
    created_by_user_id: str
    status: str
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class Character:
    character_id: str
    owner_platform: str
    owner_user_id: str
    owner_name: str
    name: str
    ruleset_key: str
    sheet_version: int
    sheet_data: dict[str, Any]
    status: str
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class CampaignCharacter:
    """A character's membership and mutable state inside one campaign."""

    campaign_id: str
    character_id: str
    alias: str | None
    state_version: int
    state_data: dict[str, Any]
    status: str
    joined_at: str
    updated_at: str
