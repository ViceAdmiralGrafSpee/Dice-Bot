"""Platform-independent dispatch for traditional text commands."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from src.chat.actions import ActionContext

# Traditional command prefixes equivalent to the ASCII dot ``.``.
_FULLWIDTH_COMMAND_PREFIXES = ("。", "．")


def normalize_command_text(text: str) -> str:
    """Normalize a leading fullwidth/ideographic full stop to ``.``.

    Only the first character after leading whitespace is inspected, so
    ordinary text such as ``今天跑团。很好玩`` keeps its full stop and can
    never be mistaken for a command.  The result is stripped of leading and
    trailing whitespace.
    """
    stripped = text.strip()
    if stripped[:1] in _FULLWIDTH_COMMAND_PREFIXES:
        return "." + stripped[1:]
    return stripped


@dataclass(frozen=True, slots=True)
class CommandRequest:
    """A parsed traditional command without any platform event object."""

    name: str
    arguments: str
    raw_text: str
    context: ActionContext = field(default_factory=ActionContext)


@dataclass(frozen=True, slots=True)
class CommandResult:
    """Text produced directly by a traditional command."""

    content: str


@dataclass(frozen=True, slots=True)
class CommandInfo:
    """Read-only help metadata for one canonical traditional command."""

    name: str
    aliases: tuple[str, ...]
    category: str | None
    description: str | None
    usage: str | None


CommandHandler = Callable[
    [CommandRequest],
    CommandResult | Awaitable[CommandResult],
]


@dataclass(slots=True)
class CommandRegistry:
    """Register and dispatch dot-prefixed traditional commands."""

    _handlers: dict[str, CommandHandler] = field(default_factory=dict)
    _categories: dict[str, str] = field(default_factory=dict)
    _descriptions: dict[str, str] = field(default_factory=dict)
    _usages: dict[str, str] = field(default_factory=dict)
    _canonical_names: dict[str, str] = field(default_factory=dict)

    def register(
        self,
        name: str,
        handler: CommandHandler,
        *,
        aliases: tuple[str, ...] = (),
        category: str | None = None,
        description: str | None = None,
        usage: str | None = None,
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
        normalized_category = category.strip() if category else ""
        canonical_name = normalized_names[0]
        for item in normalized_names:
            self._handlers[item] = handler
            self._canonical_names[item] = canonical_name
            if category is not None:
                self._categories[item] = normalized_category
            if description is not None:
                self._descriptions[item] = description
            if usage is not None:
                self._usages[item] = usage

    def names_for_category(self, category: str) -> set[str]:
        """Return the normalized names registered under ``category``."""
        return {
            name
            for name, registered_category in self._categories.items()
            if registered_category == category.strip()
        }

    def command_info(self, name: str) -> CommandInfo | None:
        """Return metadata for a canonical command, resolving aliases.

        The query accepts ``.dicecmd``, ``。dicecmd``, ``．dicecmd`` or a bare
        ``dicecmd``, and resolves aliases to the canonical command metadata.
        """
        normalized = self._normalize_query(name)
        canonical_name = self._canonical_names.get(normalized)
        if canonical_name is None:
            return None
        aliases = tuple(
            alias
            for alias, canonical in self._canonical_names.items()
            if canonical == canonical_name and alias != canonical_name
        )
        return CommandInfo(
            name=canonical_name,
            aliases=aliases,
            category=self._categories.get(canonical_name),
            description=self._descriptions.get(canonical_name),
            usage=self._usages.get(canonical_name),
        )

    def command_infos(self) -> tuple[CommandInfo, ...]:
        """Return metadata for every canonical command, without aliases."""
        canonical_names = sorted(
            set(self._canonical_names.values()),
            key=len,
        )
        canonical_names.sort()
        infos: list[CommandInfo] = []
        for canonical_name in canonical_names:
            info = self.command_info(canonical_name)
            if info is not None:
                infos.append(info)
        return tuple(infos)

    async def dispatch(
        self,
        text: str,
        context: ActionContext | None = None,
    ) -> CommandResult | None:
        """Await a command handler, or return ``None`` when none matches."""

        stripped = normalize_command_text(text)
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
                context=context or ActionContext(),
            )
            result = self._handlers[name](request)
            if inspect.isawaitable(result):
                return await result
            return result
        return None

    @staticmethod
    def _normalize_name(name: str) -> str:
        normalized = name.strip().removeprefix(".").lower()
        if not normalized or any(character.isspace() for character in normalized):
            raise ValueError("命令名不能为空或包含空白")
        return normalized

    @classmethod
    def _normalize_query(cls, name: str) -> str:
        normalized = normalize_command_text(name).lower()
        return normalized.removeprefix(".")

    @staticmethod
    def _is_argument_boundary(character: str) -> bool:
        # Traditional dice syntax commonly permits both `.r 1d100` and
        # `.r1d100`. Keeping digit/dice boundaries also avoids treating
        # ordinary text such as `.random` as the registered `.r` command.
        return character.isspace() or character.isdigit() or character in "dD"


def _format_command_help(info: CommandInfo) -> list[str]:
    names = " / ".join(f".{name}" for name in (info.name, *info.aliases))
    lines = [names]
    if info.description:
        lines.append(info.description)
    if info.usage:
        lines.append("用法：")
        for line in info.usage.splitlines():
            lines.append(line)
    return lines


def register_help_command(registry: CommandRegistry) -> None:
    """Register the deterministic ``.help`` traditional command.

    This command lists only canonical commands that carry help metadata.  It
    never consults LLM tool routing or any dynamic capability summary.
    """
    if registry.command_info("help") is not None:
        return

    def handle_help(request: CommandRequest) -> CommandResult:
        query = request.arguments.strip()
        if query:
            info = registry.command_info(query)
            if info is None:
                normalized_query = normalize_command_text(query)
                display = (
                    normalized_query
                    if normalized_query.startswith(".")
                    else f".{normalized_query}"
                )
                return CommandResult(
                    f"没有找到 `{display}` 这个命令。使用 `.help` 查看当前命令列表。"
                )
            return CommandResult("\n".join(_format_command_help(info)))

        infos = [
            info
            for info in registry.command_infos()
            if info.description is not None or info.usage is not None
        ]
        lines = ["统治地位 · 命令帮助"]
        for info in infos:
            lines.extend(_format_command_help(info))
            lines.append("")
        lines.append("查看单条命令：")
        lines.append(".help dicecmd")
        return CommandResult("\n".join(lines))

    registry.register("help", handle_help, aliases=("h",))