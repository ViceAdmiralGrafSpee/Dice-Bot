"""Platform-independent dispatch for traditional text commands."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True, slots=True)
class CommandRequest:
    """A parsed traditional command without any platform event object."""

    name: str
    arguments: str
    raw_text: str


@dataclass(frozen=True, slots=True)
class CommandResult:
    """Text produced directly by a traditional command."""

    content: str


class CommandHandler(Protocol):
    def __call__(self, request: CommandRequest) -> CommandResult: ...


@dataclass(slots=True)
class CommandRegistry:
    """Register and dispatch dot-prefixed traditional commands."""

    _handlers: dict[str, CommandHandler] = field(default_factory=dict)

    def register(
        self,
        name: str,
        handler: CommandHandler,
        *,
        aliases: tuple[str, ...] = (),
    ) -> None:
        names = (name, *aliases)
        normalized_names = tuple(self._normalize_name(item) for item in names)
        if len(set(normalized_names)) != len(normalized_names):
            raise ValueError("同一命令不能重复注册名称或别名")
        duplicate = next(
            (item for item in normalized_names if item in self._handlers),
            None,
        )
        if duplicate is not None:
            raise ValueError(f"命令已注册：.{duplicate}")
        for item in normalized_names:
            self._handlers[item] = handler

    def dispatch(self, text: str) -> CommandResult | None:
        """Return ``None`` when text does not match a registered command."""

        stripped = text.strip()
        if not stripped.startswith("."):
            return None

        command_text = stripped[1:]
        for name in sorted(self._handlers, key=len, reverse=True):
            if not command_text.lower().startswith(name):
                continue
            remainder = command_text[len(name) :]
            if remainder and not self._is_argument_boundary(remainder[0]):
                continue
            request = CommandRequest(
                name=name,
                arguments=remainder.strip(),
                raw_text=stripped,
            )
            return self._handlers[name](request)
        return None

    @staticmethod
    def _normalize_name(name: str) -> str:
        normalized = name.strip().removeprefix(".").lower()
        if not normalized or any(character.isspace() for character in normalized):
            raise ValueError("命令名不能为空或包含空白")
        return normalized

    @staticmethod
    def _is_argument_boundary(character: str) -> bool:
        # Traditional dice syntax commonly permits both `.r 1d100` and
        # `.r1d100`. Keeping digit/dice boundaries also avoids treating
        # ordinary text such as `.random` as the registered `.r` command.
        return character.isspace() or character.isdigit() or character in "dD"
