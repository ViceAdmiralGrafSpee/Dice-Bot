"""Tests for deterministic ``.help``, command metadata, and fullwidth prefixes.

Covers:

1. CommandRegistry help metadata and public read-only APIs
2. deterministic ``.help`` / ``.help <command>`` output
3. Chinese/ideographic full stop prefixes (``。`` / ``．``) as equals of ``.``
4. combined require-at / targeting behavior for fullwidth commands
5. ordinary chat text never being mis-recognized or globally rewritten
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from src.chat.commands import (
    CommandRegistry,
    CommandRequest,
    CommandResult,
    normalize_command_text,
    register_help_command,
)
from src.chat.dice.gate import (
    DiceCategoryGate,
    QQ_SENDER_ROLE,
    is_dice_category_command,
    is_dicecmd_command,
)
from src.chat.platform import ConversationContext, ConversationKind, IncomingMessage
from src.chat.platform.onebot.command_policy import (
    RequireAtPolicy,
    register_cmdat_command,
)

BOT_ID = "bot-1"
OTHER_ID = "123456"
GROUP_ID = "group-1"
USER_ID = "10001"
ADMIN_IDS = ["10001"]


class RecordingHandler:
    def __init__(self, messages: list[str]) -> None:
        self.messages = messages

    def __call__(self, request: CommandRequest) -> CommandResult:
        self.messages.append(f"{request.name}:{request.arguments}")
        return CommandResult(f"received: {request.arguments}")


def _help_registry(*, with_help: bool = True) -> CommandRegistry:
    registry = CommandRegistry()
    registry.register(
        "r",
        RecordingHandler([]),
        aliases=("roll",),
        category="dice",
        description="通用骰点",
        usage=(".r1d20\n.r 2d6+3\n.roll 1d100\n.rd20"),
    )
    registry.register(
        "dnd5e",
        RecordingHandler([]),
        category="dice",
        description="DND 5e 规则命令",
    )
    registry.register(
        "dicecmd",
        RecordingHandler([]),
        description="控制本群传统骰子/规则命令开关",
        usage=(".dicecmd status\n.dicecmd on\n.dicecmd off"),
    )
    if with_help:
        register_help_command(registry)
    return registry


# --- Metadata registry tests -------------------------------------------------


def test_register_without_metadata_still_works() -> None:
    registry = CommandRegistry()
    messages: list[str] = []
    registry.register("legacy", RecordingHandler(messages))

    info = registry.command_info("legacy")
    assert info is not None
    assert info.name == "legacy"
    assert info.aliases == ()
    assert info.category is None
    assert info.description is None
    assert info.usage is None


def test_command_info_returns_canonical_metadata() -> None:
    registry = _help_registry()

    info = registry.command_info("r")
    assert info is not None
    assert info.name == "r"
    assert info.aliases == ("roll",)
    assert info.category == "dice"
    assert info.description == "通用骰点"
    assert ".rd20" in info.usage


def test_alias_query_returns_canonical_metadata() -> None:
    registry = _help_registry()

    alias_info = registry.command_info("roll")
    canonical_info = registry.command_info("r")
    assert alias_info == canonical_info
    assert alias_info.name == "r"


def test_command_infos_does_not_repeat_aliases() -> None:
    registry = _help_registry()

    infos = registry.command_infos()
    names = [info.name for info in infos]

    assert names == ["dicecmd", "dnd5e", "help", "r"]

    rolled = next(info for info in infos if info.name == "r")
    assert rolled.aliases == ("roll",)

    help_info = next(info for info in infos if info.name == "help")
    assert help_info.aliases == ("h",)

    assert [info.name for info in infos if info.aliases] == ["help", "r"]


# --- .help output --------------------------------------------------------------


@pytest.mark.asyncio
async def test_help_lists_real_commands() -> None:
    registry = _help_registry()
    result = await registry.dispatch(".help")
    assert result is not None
    assert "统治地位 · 命令帮助" in result.content
    assert ".r / .roll" in result.content
    assert ".dnd5e" in result.content
    assert ".dicecmd" in result.content
    assert "查看单条命令：" in result.content
    assert ".help dicecmd" in result.content


@pytest.mark.asyncio
async def test_help_shows_roll_alias_once() -> None:
    registry = _help_registry()
    result = await registry.dispatch(".help")
    assert result is not None
    assert result.content.count(".r / .roll") == 1
    # The alias must never appear as a separate command line.
    assert "\n.roll\n" not in result.content


@pytest.mark.asyncio
async def test_help_single_command() -> None:
    registry = _help_registry()
    result = await registry.dispatch(".help r")
    assert result is not None
    assert result.content == (
        ".r / .roll\n"
        "通用骰点\n"
        "用法：\n"
        ".r1d20\n"
        ".r 2d6+3\n"
        ".roll 1d100\n"
        ".rd20"
    )


@pytest.mark.asyncio
async def test_help_alias_equals_canonical() -> None:
    registry = _help_registry()
    canonical = await registry.dispatch(".help r")
    alias = await registry.dispatch(".help roll")
    assert canonical is not None
    assert alias is not None
    assert alias.content == canonical.content


@pytest.mark.asyncio
async def test_help_with_dot_prefix() -> None:
    registry = _help_registry()
    result = await registry.dispatch(".help .dicecmd")
    assert result is not None
    assert ".dicecmd" in result.content
    assert "控制本群传统骰子/规则命令开关" in result.content
    assert ".dicecmd status" in result.content


@pytest.mark.asyncio
async def test_help_unknown_command() -> None:
    registry = _help_registry()
    result = await registry.dispatch(".help abc")
    assert result is not None
    assert result.content == "没有找到 `.abc` 这个命令。使用 `.help` 查看当前命令列表。"


@pytest.mark.asyncio
async def test_help_works_when_dice_gate_closed(tmp_path) -> None:
    gate = DiceCategoryGate(tmp_path / "gate.sqlite3", admin_ids=ADMIN_IDS)
    await gate.initialize()
    await gate.set_enabled(GROUP_ID, False, actor_user_id=USER_ID, actor_role="owner")

    registry = _help_registry()
    # .help is not in the dice category, so the closed gate must not block it.
    assert is_dice_category_command(".help", registry) is False
    result = await registry.dispatch(".help")
    assert result is not None
    assert "统治地位 · 命令帮助" in result.content


@pytest.mark.asyncio
async def test_help_fullwidth_query_prefix() -> None:
    registry = _help_registry()
    result = await registry.dispatch(".help 。dicecmd")
    assert result is not None
    assert "控制本群传统骰子/规则命令开关" in result.content


# --- Fullwidth / ideographic command prefixes ---------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("text", "expected_name", "expected_arguments"),
    [
        ("。r1d6", "r", "1d6"),
        ("．r1d6", "r", "1d6"),
        ("。r 1d20", "r", "1d20"),
        ("。roll 2d6+3", "roll", "2d6+3"),
        ("。rd20", "r", "d20"),
    ],
)
async def test_fullwidth_prefix_dispatches_like_dot(
    text: str, expected_name: str, expected_arguments: str
) -> None:
    messages: list[str] = []
    registry = CommandRegistry()
    registry.register("r", RecordingHandler(messages), aliases=("roll",), category="dice")

    result = await registry.dispatch(text)
    assert result is not None
    assert result.content == f"received: {expected_arguments}"
    assert messages == [f"{expected_name}:{expected_arguments}"]


@pytest.mark.asyncio
async def test_fullwidth_rd20_uses_existing_rd20_compat() -> None:
    messages: list[str] = []
    registry = CommandRegistry()
    registry.register("r", RecordingHandler(messages), aliases=("roll",), category="dice")

    result = await registry.dispatch("。rd20")
    assert result is not None
    assert messages == ["r:d20"]


@pytest.mark.asyncio
async def test_fullwidth_help_executes() -> None:
    registry = _help_registry()

    result = await registry.dispatch("。help")
    assert result is not None
    assert "统治地位 · 命令帮助" in result.content

    result = await registry.dispatch("．help")
    assert result is not None
    assert "统治地位 · 命令帮助" in result.content


def test_fullwidth_dicecmd_is_recognized() -> None:
    assert is_dicecmd_command("。dicecmd off") is True
    assert is_dicecmd_command("．dicecmd status") is True


@pytest.mark.asyncio
async def test_fullwidth_cmdat_is_recognized(tmp_path) -> None:
    policy = RequireAtPolicy(tmp_path / "require_at.sqlite3", admin_ids=ADMIN_IDS)
    await policy.initialize()
    registry = CommandRegistry()
    register_cmdat_command(registry, policy)
    context = SimpleNamespace(conversation_id=GROUP_ID, user_id=USER_ID)

    token = QQ_SENDER_ROLE.set("owner")
    try:
        result = await registry.dispatch("。cmdat on", context=context)
    finally:
        QQ_SENDER_ROLE.reset(token)

    assert result is not None
    assert "已开启" in result.content
    assert await policy.is_required(GROUP_ID) is True


def test_fullwidth_dnd5e_is_recognized() -> None:
    registry = CommandRegistry()
    registry.register("dnd5e", RecordingHandler([]), category="dice")
    assert is_dice_category_command("。dnd5e check +5", registry) is True


# --- require-at / targeting combinations --------------------------------------


def _group_event(
    *,
    text: str = ".r1d6",
    segments: list[dict] | None = None,
) -> dict:
    if segments is None:
        segments = [{"type": "text", "data": {"text": text}}]
    return {
        "post_type": "message",
        "message_type": "group",
        "group_id": GROUP_ID,
        "user_id": USER_ID,
        "self_id": BOT_ID,
        "message": segments,
        "raw_message": text,
        "sender": {"user_id": USER_ID, "role": "member"},
    }


def _incoming(text: str) -> IncomingMessage:
    return IncomingMessage(
        platform="qq",
        message_id="msg-1",
        user_id=USER_ID,
        user_name="测试员",
        text=text,
        conversation=ConversationContext(
            conversation_id=GROUP_ID,
            kind=ConversationKind.GROUP,
            name="测试群",
        ),
    )


def _self_at_event(*, text: str = ".r1d6") -> dict:
    return _group_event(
        text=text,
        segments=[
            {"type": "at", "data": {"qq": BOT_ID}},
            {"type": "text", "data": {"text": text}},
        ],
    )


def _other_at_event(*, text: str = ".r1d6") -> dict:
    return _group_event(
        text=f"[CQ:at,qq={OTHER_ID}]{text}",
        segments=[
            {"type": "at", "data": {"qq": OTHER_ID}},
            {"type": "text", "data": {"text": text}},
        ],
    )


async def _handle(
    event: dict,
    incoming: IncomingMessage,
    policy: RequireAtPolicy,
    registry: CommandRegistry,
    *,
    dice_gate: DiceCategoryGate | None = None,
) -> tuple[AsyncMock, bool]:
    sender = AsyncMock()
    repository = AsyncMock()
    with (
        patch(
            "src.chat.platform.onebot.persistent_chat.map_onebot_message",
            return_value=incoming,
        ),
        patch(
            "src.chat.platform.onebot.persistent_chat.is_supported_message_event",
            return_value=True,
        ),
    ):
        from src.chat.platform.onebot.persistent_chat import (
            handle_persistent_onebot_chat_event,
        )

        handled = await handle_persistent_onebot_chat_event(
            sender,
            event,
            AsyncMock(),
            repository,
            registry,
            dice_gate=dice_gate,
            require_at_policy=policy,
        )
    return sender, handled


def _require_at_policy(tmp_path) -> RequireAtPolicy:
    policy = RequireAtPolicy(tmp_path / "require_at.sqlite3", admin_ids=ADMIN_IDS)
    return policy


async def _enabled_require_at(tmp_path) -> RequireAtPolicy:
    policy = _require_at_policy(tmp_path)
    await policy.initialize()
    await policy.set_required(
        GROUP_ID, True, actor_user_id=USER_ID, actor_role="owner"
    )
    return policy


@pytest.mark.asyncio
async def test_require_at_silently_drops_bare_fullwidth_roll(tmp_path) -> None:
    policy = await _enabled_require_at(tmp_path)
    registry = CommandRegistry()
    registry.register("r", RecordingHandler([]), category="dice")

    sender, handled = await _handle(
        _group_event(text="。r1d6"), _incoming("。r1d6"), policy, registry
    )
    assert handled is True
    sender.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_require_at_allows_self_at_fullwidth_roll(tmp_path) -> None:
    policy = await _enabled_require_at(tmp_path)
    registry = CommandRegistry()
    registry.register(
        "r",
        lambda _request: SimpleNamespace(content="ROLLED"),
        category="dice",
    )

    event = _self_at_event(text="。r1d6")
    # A group owner bypasses the require-at check, proving the fullwidth
    # command is dispatched and executed rather than silently dropped.
    event["sender"] = {"user_id": USER_ID, "role": "owner"}
    sender, handled = await _handle(event, _incoming("。r1d6"), policy, registry)
    assert handled is True
    sender.send_message.assert_awaited_once_with(event, "ROLLED")


@pytest.mark.asyncio
async def test_closed_gate_still_blocks_self_at_fullwidth_roll(tmp_path) -> None:
    policy = await _enabled_require_at(tmp_path)
    gate = DiceCategoryGate(tmp_path / "gate.sqlite3", admin_ids=ADMIN_IDS)
    await gate.initialize()
    await gate.set_enabled(GROUP_ID, False, actor_user_id=USER_ID, actor_role="owner")
    registry = CommandRegistry()
    registry.register(
        "r",
        lambda _request: SimpleNamespace(content="ROLLED"),
        category="dice",
    )

    event = _self_at_event(text="。r1d6")
    # The sender must pass the require-at check first so the closed dice gate
    # is the stage that silently consumes the fullwidth dice command.
    event["sender"] = {"user_id": USER_ID, "role": "owner"}
    sender, handled = await _handle(
        event, _incoming("。r1d6"), policy, registry, dice_gate=gate
    )
    assert handled is True
    sender.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_require_at_silently_drops_bare_fullwidth_help(tmp_path) -> None:
    policy = await _enabled_require_at(tmp_path)
    registry = _help_registry()

    sender, handled = await _handle(
        _group_event(text="。help"), _incoming("。help"), policy, registry
    )
    assert handled is True
    sender.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_require_at_allows_self_at_fullwidth_help(tmp_path) -> None:
    policy = await _enabled_require_at(tmp_path)
    registry = _help_registry()

    event = _self_at_event(text="。help")
    event["sender"] = {"user_id": USER_ID, "role": "owner"}
    sender, handled = await _handle(event, _incoming("。help"), policy, registry)
    assert handled is True
    message = sender.send_message.await_args.args[1]
    assert "统治地位 · 命令帮助" in message


@pytest.mark.asyncio
async def test_other_at_fullwidth_help_is_ignored(tmp_path) -> None:
    policy = _require_at_policy(tmp_path)
    await policy.initialize()
    registry = _help_registry()

    sender, handled = await _handle(
        _other_at_event(text="。help"), _incoming("。help"), policy, registry
    )
    assert handled is True
    sender.send_message.assert_not_awaited()
    assert QQ_SENDER_ROLE.get() is None


# --- Ordinary chat text is never mis-handled ----------------------------------


@pytest.mark.asyncio
async def test_ordinary_text_with_full_stop_is_not_a_command() -> None:
    registry = _help_registry()

    assert await registry.dispatch("今天跑团。很好玩") is None
    assert await registry.dispatch("这个。r1d6只是正文") is None
    assert await registry.dispatch("。") is None


def test_normalizer_does_not_globally_replace_fullwidth_stops() -> None:
    assert normalize_command_text("今天跑团。很好玩") == "今天跑团。很好玩"
    assert normalize_command_text("这个．r1d6只是正文") == "这个．r1d6只是正文"
    assert normalize_command_text("今天跑团．很好玩") == "今天跑团．很好玩"