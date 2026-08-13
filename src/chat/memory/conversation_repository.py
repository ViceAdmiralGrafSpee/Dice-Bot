"""Small SQLite repository for recent cross-platform conversation history."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiosqlite

from src.chat.platform.models import IncomingMessage


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_MEMORY_DB_PATH = PROJECT_ROOT / "data" / "memory.sqlite3"


@dataclass(frozen=True, slots=True)
class StoredConversationMessage:
    platform: str
    conversation_id: str
    message_id: str
    author_id: str
    author_name: str
    role: str
    content: str
    created_at: str


class SQLiteConversationRepository:
    """Persist recent messages without requiring a database server.

    Raw short-term history is deliberately capped per conversation. Durable
    summaries and user facts will be a separate layer, so prompt context does
    not grow forever.
    """

    def __init__(
        self,
        db_path: str | Path = DEFAULT_MEMORY_DB_PATH,
        *,
        context_limit: int = 35,
        storage_limit: int = 500,
    ) -> None:
        if context_limit <= 0:
            raise ValueError("context_limit 必须大于 0")
        if storage_limit < context_limit:
            raise ValueError("storage_limit 不能小于 context_limit")
        self.db_path = Path(db_path)
        self.context_limit = context_limit
        self.storage_limit = storage_limit

    async def initialize(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self.db_path) as database:
            await database.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS conversation_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    platform TEXT NOT NULL,
                    conversation_id TEXT NOT NULL,
                    message_id TEXT NOT NULL,
                    author_id TEXT NOT NULL,
                    author_name TEXT NOT NULL,
                    role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(platform, conversation_id, message_id)
                );
                CREATE INDEX IF NOT EXISTS idx_conversation_messages_recent
                ON conversation_messages(platform, conversation_id, id DESC);
                """
            )
            await database.commit()

    async def record_incoming(self, message: IncomingMessage) -> None:
        await self._record(
            platform=message.platform,
            conversation_id=message.conversation.conversation_id,
            message_id=message.message_id,
            author_id=message.user_id,
            author_name=message.user_name,
            role="user",
            content=message.text,
            created_at=(message.timestamp or datetime.now(timezone.utc)).isoformat(),
        )

    async def record_assistant_reply(
        self,
        source_message: IncomingMessage,
        content: str,
        *,
        bot_id: str,
        bot_name: str,
    ) -> None:
        await self._record(
            platform=source_message.platform,
            conversation_id=source_message.conversation.conversation_id,
            message_id=f"assistant:{source_message.message_id}",
            author_id=bot_id,
            author_name=bot_name,
            role="assistant",
            content=content,
            created_at=datetime.now(timezone.utc).isoformat(),
        )

    async def _record(
        self,
        *,
        platform: str,
        conversation_id: str,
        message_id: str,
        author_id: str,
        author_name: str,
        role: str,
        content: str,
        created_at: str,
    ) -> None:
        clean_content = content.strip()
        if not clean_content:
            return

        async with aiosqlite.connect(self.db_path) as database:
            await database.execute(
                """
                INSERT OR IGNORE INTO conversation_messages (
                    platform, conversation_id, message_id, author_id,
                    author_name, role, content, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    platform,
                    conversation_id,
                    message_id,
                    author_id,
                    author_name,
                    role,
                    clean_content,
                    created_at,
                ),
            )
            await database.execute(
                """
                DELETE FROM conversation_messages
                WHERE platform = ? AND conversation_id = ?
                  AND id NOT IN (
                      SELECT id FROM conversation_messages
                      WHERE platform = ? AND conversation_id = ?
                      ORDER BY id DESC
                      LIMIT ?
                  )
                """,
                (
                    platform,
                    conversation_id,
                    platform,
                    conversation_id,
                    self.storage_limit,
                ),
            )
            await database.commit()

    async def get_recent_messages(
        self,
        message: IncomingMessage,
        *,
        exclude_message_id: str | None = None,
    ) -> list[StoredConversationMessage]:
        async with aiosqlite.connect(self.db_path) as database:
            database.row_factory = aiosqlite.Row
            cursor = await database.execute(
                """
                SELECT platform, conversation_id, message_id, author_id,
                       author_name, role, content, created_at
                FROM conversation_messages
                WHERE platform = ? AND conversation_id = ?
                  AND (? IS NULL OR message_id != ?)
                ORDER BY id DESC
                LIMIT ?
                """,
                (
                    message.platform,
                    message.conversation.conversation_id,
                    exclude_message_id,
                    exclude_message_id,
                    self.context_limit,
                ),
            )
            rows = await cursor.fetchall()

        return [StoredConversationMessage(**dict(row)) for row in reversed(rows)]

    async def get_formatted_history(
        self,
        message: IncomingMessage,
    ) -> list[dict[str, Any]]:
        messages = await self.get_recent_messages(
            message,
            exclude_message_id=message.message_id,
        )
        if not messages:
            return []

        history_text = "\n\n".join(
            f"[{stored.author_name}]: {stored.content}" for stored in messages
        )
        return [
            {
                "role": "user",
                "parts": [f"这是本会话最近的对话记录:\n\n{history_text}"],
            },
            {"role": "model", "parts": ["我已了解最近的对话"]},
        ]
