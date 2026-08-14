"""Async SQLite storage for platform-independent TRPG state."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import aiosqlite

from .importing.models import (
    CharacterDraft,
    CharacterDraftStatus,
    StoredCharacterDraft,
)
from .importing.serialization import (
    deserialize_character_draft,
    serialize_character_draft,
)
from .models import Campaign, CampaignCharacter, Character


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TRPG_DB_PATH = PROJECT_ROOT / "data" / "trpg.sqlite3"
CURRENT_SCHEMA_VERSION = 2


class SQLiteTrpgRepository:
    """Store TRPG facts without depending on QQ, Discord, or an LLM.

    Characters are independent records. A many-to-many membership table joins
    them to campaigns and keeps campaign-specific state, so one character can
    participate in several campaigns without copying the whole character.
    """

    def __init__(self, db_path: str | Path = DEFAULT_TRPG_DB_PATH) -> None:
        self.db_path = Path(db_path)

    async def initialize(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self.db_path) as database:
            await self._configure_connection(database)
            await database.execute(
                """
                CREATE TABLE IF NOT EXISTS trpg_schema_migrations (
                    version INTEGER PRIMARY KEY,
                    applied_at TEXT NOT NULL
                )
                """
            )
            cursor = await database.execute(
                "SELECT COALESCE(MAX(version), 0) AS version "
                "FROM trpg_schema_migrations"
            )
            row = await cursor.fetchone()
            installed_version = int(row[0])
            if installed_version > CURRENT_SCHEMA_VERSION:
                raise RuntimeError(
                    "TRPG 数据库版本高于当前程序，不能安全打开："
                    f"{installed_version} > {CURRENT_SCHEMA_VERSION}"
                )
            if installed_version < 1:
                await self._apply_schema_version_1(database)
            if installed_version < 2:
                await self._apply_schema_version_2(database)
            await database.commit()

    async def create_campaign(
        self,
        *,
        name: str,
        ruleset_key: str,
        platform: str,
        conversation_id: str,
        created_by_user_id: str,
        campaign_id: str | None = None,
    ) -> Campaign:
        values = {
            "campaign_id": _clean_required(campaign_id or uuid4().hex, "campaign_id"),
            "name": _clean_required(name, "name"),
            "ruleset_key": _clean_required(ruleset_key, "ruleset_key").lower(),
            "platform": _clean_required(platform, "platform").lower(),
            "conversation_id": _clean_required(conversation_id, "conversation_id"),
            "created_by_user_id": _clean_required(
                created_by_user_id, "created_by_user_id"
            ),
        }
        timestamp = _utc_now()
        async with aiosqlite.connect(self.db_path) as database:
            await self._configure_connection(database)
            await database.execute(
                """
                INSERT INTO campaigns (
                    campaign_id, name, ruleset_key, platform, conversation_id,
                    created_by_user_id, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'active', ?, ?)
                """,
                (
                    values["campaign_id"],
                    values["name"],
                    values["ruleset_key"],
                    values["platform"],
                    values["conversation_id"],
                    values["created_by_user_id"],
                    timestamp,
                    timestamp,
                ),
            )
            await database.commit()
        campaign = await self.get_campaign(values["campaign_id"])
        assert campaign is not None
        return campaign

    async def get_campaign(self, campaign_id: str) -> Campaign | None:
        async with aiosqlite.connect(self.db_path) as database:
            await self._configure_connection(database)
            database.row_factory = aiosqlite.Row
            cursor = await database.execute(
                """
                SELECT campaign_id, name, ruleset_key, platform,
                       conversation_id, created_by_user_id, status,
                       created_at, updated_at
                FROM campaigns
                WHERE campaign_id = ?
                """,
                (campaign_id,),
            )
            row = await cursor.fetchone()
        return Campaign(**dict(row)) if row else None

    async def create_character(
        self,
        *,
        owner_platform: str,
        owner_user_id: str,
        owner_name: str,
        name: str,
        ruleset_key: str,
        sheet_data: Mapping[str, Any] | None = None,
        sheet_version: int = 1,
        character_id: str | None = None,
    ) -> Character:
        if sheet_version <= 0:
            raise ValueError("sheet_version 必须大于 0")
        values = {
            "character_id": _clean_required(
                character_id or uuid4().hex, "character_id"
            ),
            "owner_platform": _clean_required(
                owner_platform, "owner_platform"
            ).lower(),
            "owner_user_id": _clean_required(owner_user_id, "owner_user_id"),
            "owner_name": _clean_required(owner_name, "owner_name"),
            "name": _clean_required(name, "name"),
            "ruleset_key": _clean_required(ruleset_key, "ruleset_key").lower(),
        }
        serialized_sheet = _serialize_object(sheet_data or {}, "sheet_data")
        timestamp = _utc_now()
        async with aiosqlite.connect(self.db_path) as database:
            await self._configure_connection(database)
            await database.execute(
                """
                INSERT INTO characters (
                    character_id, owner_platform, owner_user_id, owner_name,
                    name, ruleset_key, sheet_version, sheet_data_json,
                    status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?)
                """,
                (
                    values["character_id"],
                    values["owner_platform"],
                    values["owner_user_id"],
                    values["owner_name"],
                    values["name"],
                    values["ruleset_key"],
                    sheet_version,
                    serialized_sheet,
                    timestamp,
                    timestamp,
                ),
            )
            await database.commit()
        character = await self.get_character(values["character_id"])
        assert character is not None
        return character

    async def get_character(self, character_id: str) -> Character | None:
        async with aiosqlite.connect(self.db_path) as database:
            await self._configure_connection(database)
            database.row_factory = aiosqlite.Row
            cursor = await database.execute(
                """
                SELECT character_id, owner_platform, owner_user_id, owner_name,
                       name, ruleset_key, sheet_version, sheet_data_json,
                       status, created_at, updated_at
                FROM characters
                WHERE character_id = ?
                """,
                (character_id,),
            )
            row = await cursor.fetchone()
        return _row_to_character(row) if row else None

    async def list_characters_for_owner(
        self,
        *,
        owner_platform: str,
        owner_user_id: str,
        status: str = "active",
    ) -> list[Character]:
        """List one user's characters without exposing another user's cards."""

        clean_platform = _clean_required(
            owner_platform, "owner_platform"
        ).lower()
        clean_user_id = _clean_required(owner_user_id, "owner_user_id")
        clean_status = _clean_required(status, "status").lower()
        async with aiosqlite.connect(self.db_path) as database:
            await self._configure_connection(database)
            database.row_factory = aiosqlite.Row
            cursor = await database.execute(
                """
                SELECT character_id, owner_platform, owner_user_id, owner_name,
                       name, ruleset_key, sheet_version, sheet_data_json,
                       status, created_at, updated_at
                FROM characters
                WHERE owner_platform = ? AND owner_user_id = ? AND status = ?
                ORDER BY created_at, character_id
                """,
                (clean_platform, clean_user_id, clean_status),
            )
            rows = await cursor.fetchall()
        return [_row_to_character(row) for row in rows]

    async def archive_character_for_owner(
        self,
        *,
        character_id: str,
        owner_platform: str,
        owner_user_id: str,
    ) -> Character | None:
        """Archive one owned character while preserving provenance and links."""

        clean_character_id = _clean_required(character_id, "character_id")
        clean_platform = _clean_required(
            owner_platform, "owner_platform"
        ).lower()
        clean_user_id = _clean_required(owner_user_id, "owner_user_id")
        timestamp = _utc_now()
        async with aiosqlite.connect(self.db_path) as database:
            await self._configure_connection(database)
            database.row_factory = aiosqlite.Row
            await database.execute(
                """
                UPDATE characters
                SET status = 'archived', updated_at = ?
                WHERE character_id = ?
                  AND owner_platform = ?
                  AND owner_user_id = ?
                  AND status != 'archived'
                """,
                (
                    timestamp,
                    clean_character_id,
                    clean_platform,
                    clean_user_id,
                ),
            )
            cursor = await database.execute(
                """
                SELECT character_id, owner_platform, owner_user_id, owner_name,
                       name, ruleset_key, sheet_version, sheet_data_json,
                       status, created_at, updated_at
                FROM characters
                WHERE character_id = ?
                  AND owner_platform = ?
                  AND owner_user_id = ?
                """,
                (clean_character_id, clean_platform, clean_user_id),
            )
            row = await cursor.fetchone()
            await database.commit()
        return _row_to_character(row) if row else None

    async def save_character_draft(
        self,
        *,
        draft: CharacterDraft,
        owner_platform: str,
        owner_user_id: str,
        owner_name: str,
        draft_id: str | None = None,
    ) -> StoredCharacterDraft:
        values = {
            "draft_id": _clean_required(draft_id or uuid4().hex, "draft_id"),
            "ruleset_key": _clean_required(
                draft.ruleset_key, "ruleset_key"
            ).lower(),
            "owner_platform": _clean_required(
                owner_platform, "owner_platform"
            ).lower(),
            "owner_user_id": _clean_required(owner_user_id, "owner_user_id"),
            "owner_name": _clean_required(owner_name, "owner_name"),
        }
        serialized_draft = serialize_character_draft(draft)
        timestamp = _utc_now()
        async with aiosqlite.connect(self.db_path) as database:
            await self._configure_connection(database)
            await database.execute(
                """
                INSERT INTO character_import_drafts (
                    draft_id, ruleset_key, owner_platform, owner_user_id,
                    owner_name, source_type, source_filename, source_sha256,
                    template_profile_id, draft_json, status,
                    confirmed_character_id, created_at, updated_at, confirmed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', NULL, ?, ?, NULL)
                """,
                (
                    values["draft_id"],
                    values["ruleset_key"],
                    values["owner_platform"],
                    values["owner_user_id"],
                    values["owner_name"],
                    draft.source.source_type,
                    draft.source.original_filename,
                    draft.source.sha256,
                    draft.template_profile_id,
                    serialized_draft,
                    timestamp,
                    timestamp,
                ),
            )
            await database.commit()
        stored = await self.get_character_draft(values["draft_id"])
        assert stored is not None
        return stored

    async def get_character_draft(
        self,
        draft_id: str,
    ) -> StoredCharacterDraft | None:
        async with aiosqlite.connect(self.db_path) as database:
            await self._configure_connection(database)
            database.row_factory = aiosqlite.Row
            cursor = await database.execute(
                """
                SELECT draft_id, owner_platform, owner_user_id, owner_name,
                       draft_json, status, confirmed_character_id,
                       created_at, updated_at, confirmed_at
                FROM character_import_drafts
                WHERE draft_id = ?
                """,
                (draft_id,),
            )
            row = await cursor.fetchone()
        return _row_to_stored_draft(row) if row else None

    async def create_character_from_draft(
        self,
        *,
        draft_id: str,
        owner_platform: str,
        owner_user_id: str,
        owner_name: str,
        name: str,
        ruleset_key: str,
        sheet_data: Mapping[str, Any],
        sheet_version: int = 1,
        character_id: str | None = None,
    ) -> Character:
        """Atomically confirm a draft and create one formal character."""

        if sheet_version <= 0:
            raise ValueError("sheet_version 必须大于 0")
        values = {
            "draft_id": _clean_required(draft_id, "draft_id"),
            "character_id": _clean_required(
                character_id or uuid4().hex, "character_id"
            ),
            "owner_platform": _clean_required(
                owner_platform, "owner_platform"
            ).lower(),
            "owner_user_id": _clean_required(owner_user_id, "owner_user_id"),
            "owner_name": _clean_required(owner_name, "owner_name"),
            "name": _clean_required(name, "name"),
            "ruleset_key": _clean_required(ruleset_key, "ruleset_key").lower(),
        }
        serialized_sheet = _serialize_object(sheet_data, "sheet_data")
        timestamp = _utc_now()

        async with aiosqlite.connect(self.db_path) as database:
            await self._configure_connection(database)
            database.row_factory = aiosqlite.Row
            try:
                await database.execute("BEGIN IMMEDIATE")
                draft_cursor = await database.execute(
                    """
                    SELECT ruleset_key, owner_platform, owner_user_id, status,
                           confirmed_character_id
                    FROM character_import_drafts
                    WHERE draft_id = ?
                    """,
                    (values["draft_id"],),
                )
                draft_row = await draft_cursor.fetchone()
                if draft_row is None:
                    raise KeyError(f"找不到角色导入草稿：{values['draft_id']}")
                if (
                    draft_row["owner_platform"] != values["owner_platform"]
                    or draft_row["owner_user_id"] != values["owner_user_id"]
                ):
                    raise PermissionError("不能确认其他用户的角色导入草稿")
                if draft_row["ruleset_key"] != values["ruleset_key"]:
                    raise ValueError("草稿与角色服务的规则系统不一致")

                confirmed_character_id = draft_row["confirmed_character_id"]
                if confirmed_character_id is not None:
                    character_cursor = await database.execute(
                        """
                        SELECT character_id, owner_platform, owner_user_id,
                               owner_name, name, ruleset_key, sheet_version,
                               sheet_data_json, status, created_at, updated_at
                        FROM characters
                        WHERE character_id = ?
                        """,
                        (confirmed_character_id,),
                    )
                    character_row = await character_cursor.fetchone()
                    if character_row is None:
                        raise RuntimeError("草稿已确认，但关联角色不存在")
                    await database.rollback()
                    return _row_to_character(character_row)
                if draft_row["status"] != CharacterDraftStatus.PENDING.value:
                    raise ValueError(f"草稿状态不能确认：{draft_row['status']}")

                await database.execute(
                    """
                    INSERT INTO characters (
                        character_id, owner_platform, owner_user_id, owner_name,
                        name, ruleset_key, sheet_version, sheet_data_json,
                        status, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?)
                    """,
                    (
                        values["character_id"],
                        values["owner_platform"],
                        values["owner_user_id"],
                        values["owner_name"],
                        values["name"],
                        values["ruleset_key"],
                        sheet_version,
                        serialized_sheet,
                        timestamp,
                        timestamp,
                    ),
                )
                await database.execute(
                    """
                    UPDATE character_import_drafts
                    SET status = 'confirmed', confirmed_character_id = ?,
                        updated_at = ?, confirmed_at = ?
                    WHERE draft_id = ? AND status = 'pending'
                    """,
                    (
                        values["character_id"],
                        timestamp,
                        timestamp,
                        values["draft_id"],
                    ),
                )
                character_cursor = await database.execute(
                    """
                    SELECT character_id, owner_platform, owner_user_id,
                           owner_name, name, ruleset_key, sheet_version,
                           sheet_data_json, status, created_at, updated_at
                    FROM characters
                    WHERE character_id = ?
                    """,
                    (values["character_id"],),
                )
                character_row = await character_cursor.fetchone()
                await database.commit()
            except BaseException:
                await database.rollback()
                raise

        assert character_row is not None
        return _row_to_character(character_row)

    async def add_character_to_campaign(
        self,
        *,
        campaign_id: str,
        character_id: str,
        alias: str | None = None,
        state_data: Mapping[str, Any] | None = None,
        state_version: int = 1,
    ) -> CampaignCharacter:
        if state_version <= 0:
            raise ValueError("state_version 必须大于 0")
        clean_alias = alias.strip() if alias and alias.strip() else None
        serialized_state = _serialize_object(state_data or {}, "state_data")
        timestamp = _utc_now()
        async with aiosqlite.connect(self.db_path) as database:
            await self._configure_connection(database)
            database.row_factory = aiosqlite.Row
            campaign_cursor = await database.execute(
                "SELECT ruleset_key FROM campaigns WHERE campaign_id = ?",
                (campaign_id,),
            )
            campaign = await campaign_cursor.fetchone()
            if campaign is None:
                raise KeyError(f"找不到 Campaign：{campaign_id}")
            character_cursor = await database.execute(
                "SELECT ruleset_key, status FROM characters WHERE character_id = ?",
                (character_id,),
            )
            character = await character_cursor.fetchone()
            if character is None:
                raise KeyError(f"找不到 Character：{character_id}")
            if character["status"] != "active":
                raise ValueError("已归档的角色不能加入 Campaign")
            if campaign["ruleset_key"] != character["ruleset_key"]:
                raise ValueError(
                    "角色与 Campaign 的规则系统不一致："
                    f"{character['ruleset_key']} != {campaign['ruleset_key']}"
                )
            await database.execute(
                """
                INSERT INTO campaign_characters (
                    campaign_id, character_id, alias, state_version,
                    state_data_json, status, joined_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 'active', ?, ?)
                """,
                (
                    campaign_id,
                    character_id,
                    clean_alias,
                    state_version,
                    serialized_state,
                    timestamp,
                    timestamp,
                ),
            )
            await database.commit()
        membership = await self.get_campaign_character(campaign_id, character_id)
        assert membership is not None
        return membership

    async def get_campaign_character(
        self,
        campaign_id: str,
        character_id: str,
    ) -> CampaignCharacter | None:
        async with aiosqlite.connect(self.db_path) as database:
            await self._configure_connection(database)
            database.row_factory = aiosqlite.Row
            cursor = await database.execute(
                """
                SELECT campaign_id, character_id, alias, state_version,
                       state_data_json, status, joined_at, updated_at
                FROM campaign_characters
                WHERE campaign_id = ? AND character_id = ?
                """,
                (campaign_id, character_id),
            )
            row = await cursor.fetchone()
        return _row_to_membership(row) if row else None

    async def list_characters_for_campaign(
        self,
        campaign_id: str,
    ) -> list[CampaignCharacter]:
        async with aiosqlite.connect(self.db_path) as database:
            await self._configure_connection(database)
            database.row_factory = aiosqlite.Row
            cursor = await database.execute(
                """
                SELECT campaign_id, character_id, alias, state_version,
                       state_data_json, status, joined_at, updated_at
                FROM campaign_characters
                WHERE campaign_id = ?
                ORDER BY joined_at, character_id
                """,
                (campaign_id,),
            )
            rows = await cursor.fetchall()
        return [_row_to_membership(row) for row in rows]

    async def list_campaigns_for_character(
        self,
        character_id: str,
    ) -> list[CampaignCharacter]:
        async with aiosqlite.connect(self.db_path) as database:
            await self._configure_connection(database)
            database.row_factory = aiosqlite.Row
            cursor = await database.execute(
                """
                SELECT campaign_id, character_id, alias, state_version,
                       state_data_json, status, joined_at, updated_at
                FROM campaign_characters
                WHERE character_id = ?
                ORDER BY joined_at, campaign_id
                """,
                (character_id,),
            )
            rows = await cursor.fetchall()
        return [_row_to_membership(row) for row in rows]

    @staticmethod
    async def _configure_connection(database: aiosqlite.Connection) -> None:
        await database.execute("PRAGMA foreign_keys = ON")
        await database.execute("PRAGMA busy_timeout = 5000")

    @staticmethod
    async def _apply_schema_version_1(database: aiosqlite.Connection) -> None:
        await database.executescript(
            """
            PRAGMA journal_mode = WAL;

            CREATE TABLE IF NOT EXISTS campaigns (
                campaign_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                ruleset_key TEXT NOT NULL,
                platform TEXT NOT NULL,
                conversation_id TEXT NOT NULL,
                created_by_user_id TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_campaigns_location
            ON campaigns(platform, conversation_id, status);

            CREATE TABLE IF NOT EXISTS characters (
                character_id TEXT PRIMARY KEY,
                owner_platform TEXT NOT NULL,
                owner_user_id TEXT NOT NULL,
                owner_name TEXT NOT NULL,
                name TEXT NOT NULL,
                ruleset_key TEXT NOT NULL,
                sheet_version INTEGER NOT NULL CHECK(sheet_version > 0),
                sheet_data_json TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_characters_owner
            ON characters(owner_platform, owner_user_id, status);

            CREATE TABLE IF NOT EXISTS campaign_characters (
                campaign_id TEXT NOT NULL,
                character_id TEXT NOT NULL,
                alias TEXT,
                state_version INTEGER NOT NULL CHECK(state_version > 0),
                state_data_json TEXT NOT NULL,
                status TEXT NOT NULL,
                joined_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY(campaign_id, character_id),
                FOREIGN KEY(campaign_id) REFERENCES campaigns(campaign_id)
                    ON DELETE RESTRICT,
                FOREIGN KEY(character_id) REFERENCES characters(character_id)
                    ON DELETE RESTRICT
            );

            CREATE INDEX IF NOT EXISTS idx_campaign_characters_character
            ON campaign_characters(character_id, status);
            """
        )
        await database.execute(
            """
            INSERT OR IGNORE INTO trpg_schema_migrations(version, applied_at)
            VALUES (?, ?)
            """,
            (1, _utc_now()),
        )

    @staticmethod
    async def _apply_schema_version_2(database: aiosqlite.Connection) -> None:
        await database.executescript(
            """
            CREATE TABLE IF NOT EXISTS character_import_drafts (
                draft_id TEXT PRIMARY KEY,
                ruleset_key TEXT NOT NULL,
                owner_platform TEXT NOT NULL,
                owner_user_id TEXT NOT NULL,
                owner_name TEXT NOT NULL,
                source_type TEXT NOT NULL,
                source_filename TEXT NOT NULL,
                source_sha256 TEXT NOT NULL,
                template_profile_id TEXT,
                draft_json TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('pending', 'confirmed')),
                confirmed_character_id TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                confirmed_at TEXT,
                FOREIGN KEY(confirmed_character_id) REFERENCES characters(character_id)
                    ON DELETE RESTRICT
            );

            CREATE INDEX IF NOT EXISTS idx_character_import_drafts_owner
            ON character_import_drafts(
                owner_platform, owner_user_id, status, created_at
            );
            """
        )
        await database.execute(
            """
            INSERT OR IGNORE INTO trpg_schema_migrations(version, applied_at)
            VALUES (?, ?)
            """,
            (2, _utc_now()),
        )


def _clean_required(value: str, field_name: str) -> str:
    clean_value = value.strip()
    if not clean_value:
        raise ValueError(f"{field_name} 不能为空")
    return clean_value


def _serialize_object(value: Mapping[str, Any], field_name: str) -> str:
    try:
        return json.dumps(
            dict(value),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as error:
        raise ValueError(f"{field_name} 必须是可保存的 JSON 对象") from error


def _row_to_character(row: aiosqlite.Row) -> Character:
    values = dict(row)
    values["sheet_data"] = json.loads(values.pop("sheet_data_json"))
    return Character(**values)


def _row_to_membership(row: aiosqlite.Row) -> CampaignCharacter:
    values = dict(row)
    values["state_data"] = json.loads(values.pop("state_data_json"))
    return CampaignCharacter(**values)


def _row_to_stored_draft(row: aiosqlite.Row) -> StoredCharacterDraft:
    values = dict(row)
    values["draft"] = deserialize_character_draft(values.pop("draft_json"))
    values["status"] = CharacterDraftStatus(values["status"])
    return StoredCharacterDraft(**values)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
