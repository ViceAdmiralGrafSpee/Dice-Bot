"""Minimal provider- and platform-neutral tool runtime.

Rule systems such as COC and DND can register additional ``ToolDefinition``
objects without changing ChatService, OneBot, or the AI provider layer.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from src.chat.features.tools.llm_adapters import to_gemini_tools
from src.chat.features.tools.tool_declaration import ToolDeclaration
from src.chat.services.ai.providers.provider_format import ProviderFormat


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
