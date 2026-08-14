"""Minimal async boundary for deterministic business operations."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol, TypeVar

from src.chat.platform import MessageFile, MessageFileProvider


@dataclass(frozen=True, slots=True)
class ActionContext:
    """Caller identity without a OneBot or Discord event object."""

    user_id: str | None = None
    user_name: str | None = None
    platform: str | None = None
    message_id: str | None = None
    conversation_id: str | None = None
    files: tuple[MessageFile, ...] = ()
    file_provider: MessageFileProvider | None = None


@dataclass(frozen=True, slots=True)
class ActionResult:
    """Structured state plus text whose facts are authoritative."""

    data: Mapping[str, Any]
    authoritative_output: str | None = None


ActionRequestT = TypeVar("ActionRequestT", contravariant=True)


class Action(Protocol[ActionRequestT]):
    """One deterministic operation that may wait for a database later."""

    async def execute(
        self,
        request: ActionRequestT,
        context: ActionContext,
    ) -> ActionResult: ...
