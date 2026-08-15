from dataclasses import dataclass

import pytest

from src.chat.commands import CommandRegistry, CommandRequest, CommandResult


@dataclass
class RecordingHandler:
    requests: list[CommandRequest]

    def __call__(self, request: CommandRequest) -> CommandResult:
        self.requests.append(request)
        return CommandResult(f"received: {request.arguments}")


@pytest.mark.asyncio
async def test_registers_and_dispatches_platform_independent_command() -> None:
    requests: list[CommandRequest] = []
    registry = CommandRegistry()
    registry.register("echo", RecordingHandler(requests), aliases=("say",))

    result = await registry.dispatch("  .SAY hello world  ")

    assert result == CommandResult("received: hello world")
    assert requests == [
        CommandRequest(
            name="say",
            arguments="hello world",
            raw_text=".SAY hello world",
        )
    ]


@pytest.mark.asyncio
async def test_returns_none_for_non_command_and_unregistered_command() -> None:
    registry = CommandRegistry()

    assert await registry.dispatch("ordinary chat") is None
    assert await registry.dispatch(".unknown value") is None


@pytest.mark.asyncio
async def test_awaits_async_command_handler() -> None:
    registry = CommandRegistry()

    async def handler(request: CommandRequest) -> CommandResult:
        return CommandResult(f"async: {request.arguments}")

    registry.register("wait", handler)

    assert await registry.dispatch(".wait database") == CommandResult(
        "async: database"
    )


def test_category_metadata_groups_commands_and_aliases() -> None:
    registry = CommandRegistry()
    handler = RecordingHandler([])
    registry.register(
        "r", handler, aliases=("roll",), category="dice"
    )
    registry.register("dnd5e", handler, category="dice")
    registry.register("help", handler, category="utility")

    assert registry.names_for_category("dice") == {"r", "roll", "dnd5e"}
    assert registry.names_for_category("utility") == {"help"}
    assert registry.names_for_category("missing") == set()


def test_category_is_optional() -> None:
    registry = CommandRegistry()
    handler = RecordingHandler([])
    registry.register("echo", handler)

    assert registry.names_for_category("dice") == set()


def test_rejects_duplicate_command_or_alias() -> None:
    registry = CommandRegistry()
    handler = RecordingHandler([])
    registry.register("echo", handler, aliases=("say",))

    with pytest.raises(ValueError, match="命令已注册"):
        registry.register("say", handler)
