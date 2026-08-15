"""QQ group gate for the traditional dice command category.

This module decides whether a traditional dice command (``.r`` / ``.roll`` /
``.dnd5e``) should be executed in a QQ group. When the gate is disabled the
command is silently consumed: it produces neither a dice roll nor an LLM
turn. Private messages are never affected, and LLM tool calls
(``roll_dice`` / ``dnd5e_check``) bypass the gate entirely.
"""

from __future__ import annotations

from contextvars import ContextVar
import os
from pathlib import Path
from typing import Any, Sequence

import aiosqlite

from src.chat.actions import ActionContext
from src.chat.commands import (
    CommandHandler,
    CommandRegistry,
    CommandRequest,
    CommandResult,
    normalize_command_text,
)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DICE_GATE_DB_PATH = PROJECT_ROOT / "data" / "dice_gate.sqlite3"

# OneBot group role (owner / admin / member) supplied by the QQ adapter.
# Keeping the value here (instead of on ActionContext) preserves the
# platform-neutral boundary while still letting the QQ-only control command
# reuse the same permission check.
QQ_SENDER_ROLE: ContextVar[str | None] = ContextVar(
    "qq_sender_role", default=None
)

# Categories used when reading the command registry below.
DICE_CATEGORY = "dice"

# Env var containing comma-separated administrator QQ numbers.
_QQ_BOT_ADMIN_IDS_ENV = "QQ_BOT_ADMIN_IDS"


def load_qq_bot_admin_ids(environ: dict[str, str] | None = None) -> frozenset[str]:
    """Parse ``QQ_BOT_ADMIN_IDS`` into a set of normalized QQ numbers."""
    values = dict(os.environ) if environ is None else environ
    raw = values.get(_QQ_BOT_ADMIN_IDS_ENV, "")
    return frozenset(
        item.strip()
        for item in raw.replace("，", ",").split(",")
        if item.strip()
    )


def can_manage_group(
    *,
    actor_user_id: str | None,
    actor_role: str | None,
    admin_ids: Sequence[str],
) -> bool:
    """Shared QQ group management permission used by ``.dicecmd`` / ``.cmdat``.

    A group owner, a group admin, or a configured bot admin may manage the
    QQ-only control commands.  This single implementation keeps ``.dicecmd``
    and the new ``.cmdat`` command using the exact same permission rule so the
    two control commands never diverge.
    """
    normalized = frozenset(admin_ids)
    if actor_user_id and actor_user_id in normalized:
        return True
    return actor_role in {"owner", "admin", "群主", "管理员"}


def dice_category_command_names(registry: CommandRegistry) -> set[str]:
    """Return the currently registered dice-category command names."""
    return registry.names_for_category(DICE_CATEGORY)


def is_dice_category_command(text: str, registry: CommandRegistry) -> bool:
    """Return whether ``text`` starts a registered dice-category command."""
    return _matches_registered_names(text, dice_category_command_names(registry))


def is_dicecmd_command(text: str) -> bool:
    """Return whether ``text`` is the ``.dicecmd`` control command."""
    stripped = normalize_command_text(text)
    return stripped.lower().startswith(".dicecmd")


def normalize_command_name(text: str, registry: CommandRegistry) -> str:
    """Return the normalized category command name matched by ``text``."""
    stripped = normalize_command_text(text)
    without_dot = stripped[1:].lower() if stripped.startswith(".") else stripped
    name = _match_registered_name(without_dot, dice_category_command_names(registry))
    return name or without_dot


def _matches_registered_names(text: str, names: set[str]) -> bool:
    stripped = normalize_command_text(text)
    if not stripped.startswith("."):
        return False
    without_dot = stripped[1:].lower()
    return _match_registered_name(without_dot, names) is not None


def _is_argument_boundary(character: str) -> bool:
    """Return whether ``character`` may start a command argument.

    Mirrors ``CommandRegistry._is_argument_boundary``: traditional dice
    syntax permits both ``.r 1d100`` and ``.r1d100``, while ordinary words
    such as ``.random`` must never be treated as the registered ``.r``.
    """
    return character.isspace() or character.isdigit() or character in "dD"


def _match_registered_name(without_dot: str, names: set[str]) -> str | None:
    # Try candidates longest-first, exactly like CommandRegistry.dispatch.
    # This guarantees ".roll..." is matched against "roll" before the
    # shorter ".r", and an invalid argument boundary only skips the current
    # candidate instead of rejecting the whole text.
    for name in sorted(names, key=len, reverse=True):
        if not without_dot.startswith(name):
            continue
        remainder = without_dot[len(name) :]
        if not remainder or _is_argument_boundary(remainder[0]):
            return name
    return None


class DiceCategoryGate:
    """SQLite-backed per-group switch for the traditional dice category."""

    def __init__(
        self,
        db_path: str | Path = DEFAULT_DICE_GATE_DB_PATH,
        *,
        admin_ids: Sequence[str] | None = None,
        default_enabled: bool = True,
    ) -> None:
        self.db_path = Path(db_path)
        self.default_enabled = default_enabled
        self._admin_ids = frozenset(admin_ids or ())

    async def initialize(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self.db_path) as database:
            await database.executescript(
                """
                CREATE TABLE IF NOT EXISTS dice_category_gates (
                    conversation_id TEXT PRIMARY KEY,
                    enabled INTEGER NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )
            await database.commit()

    @staticmethod
    def _to_int(value: bool) -> int:
        return 1 if value else 0

    @staticmethod
    def _to_bool(value: Any) -> bool:
        return bool(value)

    async def is_enabled(self, conversation_id: str | None) -> bool:
        """Whether traditional dice commands run for a group.

        ``None`` (or a private conversation id) is always enabled because the
        gate only applies to QQ groups.
        """
        if conversation_id is None:
            return True
        async with aiosqlite.connect(self.db_path) as database:
            async with database.execute(
                "SELECT enabled FROM dice_category_gates WHERE conversation_id = ?",
                (conversation_id,),
            ) as cursor:
                row = await cursor.fetchone()
        return self.default_enabled if row is None else self._to_bool(row[0])

    async def set_enabled(
        self,
        conversation_id: str,
        enabled: bool,
        *,
        actor_user_id: str | None,
        actor_role: str | None,
    ) -> tuple[bool, str]:
        """Update a group switch after verifying actor permission.

        Returns ``(permitted, message)``. ``permitted`` is ``False`` and the
        switch is left unchanged when the actor is neither a group owner,
        a group admin, nor a configured bot admin.
        """
        if not self._can_manage(actor_user_id=actor_user_id, actor_role=actor_role):
            return False, "权限不足：只有群主、群管理员或 Bot 管理员才能修改骰子开关。"
        async with aiosqlite.connect(self.db_path) as database:
            await database.execute(
                "INSERT INTO dice_category_gates(conversation_id, enabled, updated_at) "
                "VALUES (?, ?, ?) "
                "ON CONFLICT(conversation_id) DO UPDATE SET enabled = excluded.enabled, "
                "updated_at = excluded.updated_at",
                (conversation_id, self._to_int(enabled), _now_iso()),
            )
            await database.commit()
        state = "开启" if enabled else "关闭"
        return True, f"本群传统骰子命令已{state}。"

    def _can_manage(
        self,
        *,
        actor_user_id: str | None,
        actor_role: str | None,
    ) -> bool:
        return can_manage_group(
            actor_user_id=actor_user_id,
            actor_role=actor_role,
            admin_ids=self._admin_ids,
        )

    def create_control_handler(self) -> CommandHandler:
        """Build the ``.dicecmd on|off|status`` handler."""

        async def handle_dicecmd(request: CommandRequest) -> CommandResult:
            conversation_id = request.context.conversation_id
            if not conversation_id:
                return CommandResult("骰子开关仅支持在QQ群中使用。")
            parts = request.arguments.split()
            action = parts[0].lower() if parts else "status"

            if action == "on":
                permitted, message = await self.set_enabled(
                    conversation_id,
                    True,
                    actor_user_id=request.context.user_id,
                    actor_role=QQ_SENDER_ROLE.get(),
                )
                if not permitted:
                    return CommandResult(message)
                return CommandResult(message)
            if action == "off":
                permitted, message = await self.set_enabled(
                    conversation_id,
                    False,
                    actor_user_id=request.context.user_id,
                    actor_role=QQ_SENDER_ROLE.get(),
                )
                if not permitted:
                    return CommandResult(message)
                return CommandResult(message)
            if action == "status":
                enabled = await self.is_enabled(conversation_id)
                state = "开启" if enabled else "关闭"
                return CommandResult(f"本群传统骰子命令当前{state}。")
            return CommandResult("骰子开关命令格式：.dicecmd on / off / status")

        return handle_dicecmd


def register_dice_gate_commands(
    registry: CommandRegistry,
    gate: DiceCategoryGate,
) -> None:
    """Register ``.dicecmd`` when the gate is installed."""
    registry.register(
        "dicecmd",
        gate.create_control_handler(),
        description="控制本群传统骰子/规则命令开关",
        usage=".dicecmd status\n.dicecmd on\n.dicecmd off",
    )


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()