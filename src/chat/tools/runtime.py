"""Minimal provider- and platform-neutral tool runtime.

Rule systems such as COC and DND can register additional ``ToolDefinition``
objects without changing ChatService, OneBot, or the AI provider layer.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
import json
import logging
from typing import Any

from src.chat.features.tools.llm_adapters import to_gemini_tools
from src.chat.features.tools.tool_declaration import ToolDeclaration
from src.chat.services.ai.providers.provider_format import ProviderFormat

log = logging.getLogger(__name__)

# Attributes anywhere in a tool argument key that must not be written to logs.
_SENSITIVE_ARGUMENT_KEYWORDS = (
    "api_key",
    "apikey",
    "token",
    "secret",
    "password",
    "passwd",
    "authorization",
    "cookie",
    "credential",
    "private_key",
    "access_key",
)

# Default log length limits for LLM tool-call arguments.
MAX_TOOL_ARGUMENT_VALUE_CHARS = 500
MAX_TOOL_ARGUMENT_SUMMARY_CHARS = 2000


def _is_sensitive_argument_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_")
    return any(word in normalized for word in _SENSITIVE_ARGUMENT_KEYWORDS)


def _redact_and_limit_value(value: Any, *, max_value_chars: int) -> Any:
    """Recursively redact sensitive keys and trim long string values."""
    if isinstance(value, Mapping):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            string_key = str(key)
            if _is_sensitive_argument_key(string_key):
                redacted[string_key] = "[REDACTED]"
            else:
                redacted[string_key] = _redact_and_limit_value(
                    item,
                    max_value_chars=max_value_chars,
                )
        return redacted
    if isinstance(value, (list, tuple)):
        return [
            _redact_and_limit_value(item, max_value_chars=max_value_chars)
            for item in value
        ]
    if isinstance(value, str) and len(value) > max_value_chars:
        return (
            value[:max_value_chars]
            + f"…(截断{len(value) - max_value_chars}字符)"
        )
    return value


def format_tool_argument_summary(
    arguments: Mapping[str, Any],
    *,
    max_value_chars: int = MAX_TOOL_ARGUMENT_VALUE_CHARS,
    max_summary_chars: int = MAX_TOOL_ARGUMENT_SUMMARY_CHARS,
) -> str:
    """Build a redacted, length-limited JSON summary of tool arguments."""
    redacted = _redact_and_limit_value(
        arguments,
        max_value_chars=max_value_chars,
    )
    try:
        summary = json.dumps(redacted, ensure_ascii=False, sort_keys=True, default=str)
    except (TypeError, ValueError, UnicodeEncodeError):
        try:
            summary = json.dumps(redacted, ensure_ascii=True, sort_keys=True, default=str)
        except (TypeError, ValueError):
            summary = str(redacted)
    if len(summary) <= max_summary_chars:
        return summary
    return summary[:max_summary_chars] + f"…(截断{len(summary) - max_summary_chars}字符)"


@dataclass(frozen=True, slots=True)
class ToolExecutionContext:
    user_id: str | None = None
    user_name: str | None = None
    platform: str | None = None
    user_text: str | None = None


@dataclass(frozen=True, slots=True)
class ToolOutcome:
    """Structured result plus optional text that the LLM cannot overwrite."""

    data: Mapping[str, Any]
    authoritative_output: str | None = None


ToolHandler = Callable[
    [Mapping[str, Any], ToolExecutionContext],
    Awaitable[ToolOutcome],
]
ToolAvailability = Callable[[ToolExecutionContext], bool]


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    name: str
    description: str
    parameters: Mapping[str, Any]
    handler: ToolHandler
    category: str = "general"
    availability: ToolAvailability | None = None

    def is_available(self, context: ToolExecutionContext) -> bool:
        return self.availability is None or self.availability(context)

    def as_declaration(self) -> ToolDeclaration:
        return ToolDeclaration(
            name=self.name,
            description=self.description,
            parameters=dict(self.parameters),
            function=self.handler,
            category=self.category,
        )


@dataclass(slots=True)
class ToolRegistry:
    _definitions: dict[str, ToolDefinition] = field(default_factory=dict)

    def register(self, definition: ToolDefinition) -> None:
        if definition.name in self._definitions:
            raise ValueError(f"工具已注册：{definition.name}")
        self._definitions[definition.name] = definition

    def get(self, name: str) -> ToolDefinition | None:
        return self._definitions.get(name)

    def declarations(
        self, context: ToolExecutionContext | None = None
    ) -> list[ToolDeclaration]:
        return [
            definition.as_declaration()
            for definition in self._definitions.values()
            if context is None or definition.is_available(context)
        ]


class PortableToolService:
    """Expose registered tools in each provider's expected schema."""

    def __init__(self, registry: ToolRegistry) -> None:
        self.registry = registry

    async def get_dynamic_tools_for_context(
        self,
        _user_id_for_settings: str | None = None,
        provider_type: str | None = None,
        user_text: str | None = None,
    ) -> list[Any]:
        context = ToolExecutionContext(
            user_id=self._optional_string(_user_id_for_settings),
            user_text=self._optional_string(user_text),
        )
        declarations = self.registry.declarations(context)
        if ProviderFormat.is_gemini_provider(provider_type or ""):
            return to_gemini_tools(declarations)
        return [declaration.to_openai_format() for declaration in declarations]

    async def execute_tool_call(
        self,
        tool_call: Any,
        **kwargs: Any,
    ) -> dict[str, Any]:
        name, arguments = self._parse_call(tool_call)
        # Platform-neutral audit trail: every provider and platform logs tool
        # names and redacted, length-limited arguments through this one point.
        self._log_tool_call(name, arguments, kwargs)

        definition = self.registry.get(name)
        if definition is None:
            return {"error": f"未知工具：{name}"}

        context = ToolExecutionContext(
            user_id=self._optional_string(kwargs.get("user_id")),
            user_name=self._optional_string(kwargs.get("user_name")),
            platform=self._optional_string(kwargs.get("platform")),
            user_text=self._optional_string(kwargs.get("user_text")),
        )
        if not definition.is_available(context):
            return {"error": f"当前消息未明确请求使用工具：{name}"}
        try:
            outcome = await definition.handler(arguments, context)
        except Exception as error:
            return {"error": str(error)}

        payload: dict[str, Any] = {
            "ok": True,
            "tool": name,
            "result": dict(outcome.data),
        }
        if outcome.authoritative_output:
            payload["authoritative_output"] = outcome.authoritative_output
        return payload

    def _log_tool_call(
        self,
        name: str,
        arguments: Mapping[str, Any],
        kwargs: Mapping[str, Any],
    ) -> None:
        audit: dict[str, Any] = {
            "name": name,
            "arguments": format_tool_argument_summary(arguments),
        }
        for key in ("user_id", "platform"):
            value = kwargs.get(key)
            if value not in (None, ""):
                audit[key] = str(value)
        try:
            payload = json.dumps(audit, ensure_ascii=False, default=str)
        except (TypeError, ValueError, UnicodeEncodeError):
            payload = str(audit)
        log.info("LLM 工具调用: %s", payload)

    @staticmethod
    def _parse_call(tool_call: Any) -> tuple[str, Mapping[str, Any]]:
        if isinstance(tool_call, Mapping):
            name = str(tool_call.get("name", ""))
            arguments = tool_call.get("arguments", {})
        else:
            name = str(getattr(tool_call, "name", ""))
            raw_arguments = getattr(tool_call, "args", {})
            arguments = dict(raw_arguments) if raw_arguments else {}
        return name, arguments if isinstance(arguments, Mapping) else {}

    @staticmethod
    def _optional_string(value: Any) -> str | None:
        return None if value is None else str(value)
