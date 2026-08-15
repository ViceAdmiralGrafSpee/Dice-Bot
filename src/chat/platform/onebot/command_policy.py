"""OneBot-layer targeting and require-at policy for traditional commands.

This module stays strictly inside the OneBot adapter boundary:

- ``analyze_at_targeting`` reads the real OneBot ``at`` message segments (and
  the CQ-code fallback in ``raw_message``) instead of comparing nicknames, and
  decides whether the current bot was explicitly mentioned.
- ``RequireAtPolicy`` persists a per-group ``require_at_for_commands`` switch
  in SQLite. Private conversations always bypass the switch.
- ``.cmdat on/off/status`` is registered here as a QQ-only control command and
  reuses the same group-management permission rule as ``.dicecmd``.

The platform-neutral ``ActionContext`` and ``CommandRegistry`` never learn
about QQ ``@`` mentions.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any

import aiosqlite

from src.chat.commands import (
    CommandHandler,
    CommandRegistry,
    CommandRequest,
    CommandResult,
)
from src.chat.dice.gate import QQ_SENDER_ROLE, can_manage_group

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_REQUIRE_AT_DB_PATH = PROJECT_ROOT / "data" / "require_at.sqlite3"

_CQ_AT_PATTERN = re.compile(r"\[CQ:at,qq=([^,\]]+)[^\]]*\]")
# ``@<qq>`` / ``@全体成员`` / ``@昵称`` prefixes produced by the event mapper.
_AT_MENTION_PREFIX_PATTERN = re.compile(r"^(?:@(?:\d+|全体成员|[^\s@]+)\s*)+")


def _string(value: Any, default: str = "") -> str:
    return default if value is None else str(value)


def _segments(event: Mapping[str, Any]) -> Sequence[Mapping[str, Any]]:
    message = event.get("message")
    if not isinstance(message, Sequence) or isinstance(message, (str, bytes)):
        return ()
    return tuple(segment for segment in message if isinstance(segment, Mapping))


@dataclass(frozen=True, slots=True)
class AtTargeting:
    """Whether a group event mentions anyone and whether it mentions us."""

    has_any_at: bool = False
    includes_self: bool = False


def analyze_at_targeting(event: Mapping[str, Any]) -> AtTargeting:
    """Inspect OneBot ``at`` segments / CQ codes against the real ``self_id``.

    ``@全体成员`` (``qq=all``) is deliberately not treated as mentioning the
    current bot: an explicit ``@当前Bot`` QQ number is required.
    """
    self_id = _string(event.get("self_id"))
    mentioned_ids: set[str] = set()

    for segment in _segments(event):
        if segment.get("type") != "at":
            continue
        data = segment.get("data")
        if isinstance(data, Mapping):
            mentioned = _string(data.get("qq"))
            if mentioned:
                mentioned_ids.add(mentioned)

    raw_message = _string(event.get("raw_message") or event.get("message"))
    mentioned_ids.update(_CQ_AT_PATTERN.findall(raw_message))

    has_any_at = bool(mentioned_ids)
    includes_self = self_id in mentioned_ids
    return AtTargeting(
        has_any_at=has_any_at,
        includes_self=includes_self,
    )


def is_traditional_command(text: str) -> bool:
    """Whether ``text`` starts a traditional dot-prefixed command."""
    return text.strip().startswith(".")


def strip_at_mentions(text: str) -> str:
    """Remove leading ``@`` mentions so a command can be dispatched cleanly.

    The event mapper already drops the current bot's own ``at`` segment; when
    a message mentions several objects (one of which is the current bot) the
    remaining ``@<other>`` prefixes must not corrupt the command text handed
    to the platform-neutral ``CommandRegistry``.
    """
    return _AT_MENTION_PREFIX_PATTERN.sub("", text).strip()


class RequireAtPolicy:
    """SQLite-backed per-group ``require_at_for_commands`` switch.

    This is a QQ group policy for the whole traditional command system, not a
    dice-specific switch. Private conversations are never affected.
    """

    def __init__(
        self,
        db_path: str | Path = DEFAULT_REQUIRE_AT_DB_PATH,
        *,
        admin_ids: Sequence[str] | None = None,
        default_required: bool = False,
    ) -> None:
        self.db_path = Path(db_path)
        self.default_required = default_required
        self._admin_ids = frozenset(admin_ids or ())

    async def initialize(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self.db_path) as database:
            await database.executescript(
                """
                CREATE TABLE IF NOT EXISTS require_at_policies (
                    conversation_id TEXT PRIMARY KEY,
                    required INTEGER NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )
            await database.commit()

    @staticmethod
    def _to_int(value: bool) -> int:
        return 1 if value else 0

    @classmethod
    def _to_bool(cls, value: Any) -> bool:
        return bool(value)

    async def is_required(self, conversation_id: str | None) -> bool:
        """Whether this group requires ``@当前Bot`` before running commands.

        ``None`` and private conversations always return the default
        (``False``), so require-at never applies outside QQ groups.
        """
        if conversation_id is None:
            return self.default_required
        async with aiosqlite.connect(self.db_path) as database:
            async with database.execute(
                "SELECT required FROM require_at_policies WHERE conversation_id = ?",
                (conversation_id,),
            ) as cursor:
                row = await cursor.fetchone()
        return self.default_required if row is None else self._to_bool(row[0])

    async def set_required(
        self,
        conversation_id: str,
        required: bool,
        *,
        actor_user_id: str | None,
        actor_role: str | None,
    ) -> tuple[bool, str]:
        """Update the group switch after verifying the same permission rule.

        Returns ``(permitted, message)``. Only group owners, group admins or
        configured bot admins may change it (reusing ``.dicecmd``'s rule).
        """
        if not can_manage_group(
            actor_user_id=actor_user_id,
            actor_role=actor_role,
            admin_ids=self._admin_ids,
        ):
            return False, "权限不足：只有群主、群管理员或 Bot 管理员才能修改本设置。"
        async with aiosqlite.connect(self.db_path) as database:
            await database.execute(
                "INSERT INTO require_at_policies(conversation_id, required, updated_at) "
                "VALUES (?, ?, ?) "
                "ON CONFLICT(conversation_id) DO UPDATE SET required = excluded.required, "
                "updated_at = excluded.updated_at",
                (conversation_id, self._to_int(required), _now_iso()),
            )
            await database.commit()
        if required:
            return True, "已开启：本群传统点号命令需要 @机器人后才会执行。"
        return True, "已关闭：本群传统点号命令可直接使用，无需 @机器人。"

    def create_control_handler(self) -> CommandHandler:
        """Build the ``.cmdat on|off|status`` handler."""

        async def handle_cmdat(request: CommandRequest) -> CommandResult:
            conversation_id = request.context.conversation_id
            if not conversation_id:
                return CommandResult(".cmdat 仅支持在QQ群中使用。")
            parts = request.arguments.split()
            action = parts[0].lower() if parts else "status"

            if action == "on":
                _permitted, message = await self.set_required(
                    conversation_id,
                    True,
                    actor_user_id=request.context.user_id,
                    actor_role=QQ_SENDER_ROLE.get(),
                )
                return CommandResult(message)
            if action == "off":
                _permitted, message = await self.set_required(
                    conversation_id,
                    False,
                    actor_user_id=request.context.user_id,
                    actor_role=QQ_SENDER_ROLE.get(),
                )
                return CommandResult(message)
            if action == "status":
                required = await self.is_required(conversation_id)
                state = "需要 @机器人。" if required else "不要求 @机器人。"
                return CommandResult(f"本群传统命令当前{state}")
            return CommandResult(".cmdat 命令格式：.cmdat on / off / status")

        return handle_cmdat


def register_cmdat_command(
    registry: CommandRegistry,
    policy: RequireAtPolicy,
) -> None:
    """Register ``.cmdat`` when the require-at policy is installed."""
    registry.register("cmdat", policy.create_control_handler())


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()