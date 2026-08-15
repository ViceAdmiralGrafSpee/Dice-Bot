"""Tests for the QQ group traditional dice category gate.

Covers the ``.dicecmd on/off/status`` control command, SQLite persistence,
permission checks, and silent consumption in ``persistent_chat``.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from src.chat.commands import CommandRegistry
from src.chat.dice.gate import (
    DEFAULT_DICE_GATE_DB_PATH,
    DiceCategoryGate,
    QQ_SENDER_ROLE,
    is_dice_category_command,
    is_dicecmd_command,
    load_qq_bot_admin_ids,
    register_dice_gate_commands,
)
from src.chat.platform import ConversationContext, ConversationKind, IncomingMessage


# --- Command classification -------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        ".r",
        ".r 1d20",
        ".r1d20",
        ".roll 2d6+3",
        ".roll2d6",
        ".dnd5e",
        ".dnd5e 攻击检定",
        " .r 1d20 ",
    ],
)
def test_dice_category_commands_are_recognized(text: str) -> None:
    registry = CommandRegistry()
    registry.register("r", lambda _request: SimpleNamespace(content="ROLLED"), category="dice")
    registry.register("dnd5e", lambda _request: SimpleNamespace(content="DND"), category="dice")
    assert is_dice_category_command(text, registry) is True


@pytest.mark.parametrize(
    "text",
    [
        ".random",
        ".raw",
        ".rm",
        ".dicecmd",
        ".dicecmd off",
        ".dnd5r import",
        "r 1d20",
        "roll 1d20",
        "帮我骰 1d20",
        "",
        ".",
    ],
)
def test_dice_category_commands_are_recognized(text: str) -> None:
    registry = CommandRegistry()
    registry.register(
        "r",
        lambda _request: SimpleNamespace(content="ROLLED"),
        aliases=("roll",),
        category="dice",
    )
    registry.register(
        "dnd5e",
        lambda _request: SimpleNamespace(content="DND"),
        category="dice",
    )
    assert is_dice_category_command(text, registry) is True


@pytest.mark.parametrize(
    "text",
    [
        ".r1d6",
        ".r 1d6",
        ".roll2d6",
        ".roll 2d6+3",
        ".dnd5e check +5",
    ],
)
def test_dice_category_commands_are_recognized(text: str) -> None:
    registry = CommandRegistry()
    registry.register(
        "r",
        lambda _request: SimpleNamespace(content="ROLLED"),
        aliases=("roll",),
        category="dice",
    )
    registry.register(
        "dnd5e",
        lambda _request: SimpleNamespace(content="DND"),
        category="dice",
    )
    assert is_dice_category_command(text, registry) is True


@pytest.mark.parametrize(
    "text",
    [
        ".random",
        ".raw",
        ".rm",
        ".dicecmd",
        ".dicecmd off",
        ".dnd5r import",
        "r 1d20",
        "roll 1d20",
        "帮我骰 1d20",
        "",
        ".",
    ],
)
def test_non_dice_commands_are_not_recognized(text: str) -> None:
    registry = CommandRegistry()
    registry.register(
        "r",
        lambda _request: SimpleNamespace(content="ROLLED"),
        aliases=("roll",),
        category="dice",
    )
    registry.register(
        "dnd5e",
        lambda _request: SimpleNamespace(content="DND"),
        category="dice",
    )
    assert is_dice_category_command(text, registry) is False


def test_load_qq_bot_admin_ids_parses_environment() -> None:
    values = load_qq_bot_admin_ids(
        environ={"QQ_BOT_ADMIN_IDS": " 10001 ，10002, 10003 "}
    )
    assert values == frozenset({"10001", "10002", "10003"})


def test_load_qq_bot_admin_ids_defaults_to_empty() -> None:
    assert load_qq_bot_admin_ids(environ={}) == frozenset()


# --- SQLite gate persistence and permissions ---------------------------------


@pytest.mark.asyncio
async def test_gate_defaults_to_enabled(tmp_path) -> None:
    gate = DiceCategoryGate(tmp_path / "gate.sqlite3")
    await gate.initialize()

    assert await gate.is_enabled("group-1") is True
    assert await gate.is_enabled(None) is True


@pytest.mark.asyncio
async def test_gate_persists_switch_across_instances(tmp_path) -> None:
    path = tmp_path / "gate.sqlite3"

    gate = DiceCategoryGate(path, admin_ids=["10001"])
    await gate.initialize()
    permitted, message = await gate.set_enabled(
        "group-1",
        False,
        actor_user_id="10001",
        actor_role="member",
    )
    assert permitted is True
    assert "关闭" in message
    assert await gate.is_enabled("group-1") is False

    # A fresh instance reading the same file must see the stored switch.
    reopened = DiceCategoryGate(path, admin_ids=["10001"])
    await reopened.initialize()
    assert await reopened.is_enabled("group-1") is False
    # Other groups keep the default.
    assert await reopened.is_enabled("group-2") is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("role", "user_id"),
    [("owner", "1"), ("admin", "2"), ("群主", "3"), ("member", "10001")],
)
async def test_group_owner_admin_and_bot_admin_can_change(
    tmp_path, role: str, user_id: str
) -> None:
    gate = DiceCategoryGate(tmp_path / "gate.sqlite3", admin_ids=["10001"])
    await gate.initialize()

    permitted, _message = await gate.set_enabled(
        "group-1",
        False,
        actor_user_id=user_id,
        actor_role=role,
    )
    assert permitted is True


@pytest.mark.asyncio
async def test_ordinary_member_cannot_change_gate(tmp_path) -> None:
    gate = DiceCategoryGate(tmp_path / "gate.sqlite3", admin_ids=["10001"])
    await gate.initialize()

    permitted, message = await gate.set_enabled(
        "group-1",
        False,
        actor_user_id="20002",
        actor_role="member",
    )
    assert permitted is False
    assert "权限" in message
    # The stored switch is unchanged (still default enabled).
    assert await gate.is_enabled("group-1") is True


@pytest.mark.asyncio
async def test_dicecmd_on_off_status_through_registry(tmp_path) -> None:
    gate = DiceCategoryGate(tmp_path / "gate.sqlite3", admin_ids=["10001"])
    await gate.initialize()
    registry = CommandRegistry()
    register_dice_gate_commands(registry, gate)

    group_context = SimpleNamespace(
        conversation_id="group-1", user_id="10001"
    )

    token = QQ_SENDER_ROLE.set("owner")
    try:
        off = await registry.dispatch(
            ".dicecmd off",
            context=group_context,
        )
    finally:
        QQ_SENDER_ROLE.reset(token)
    assert off is not None and "关闭" in off.content
    assert await gate.is_enabled("group-1") is False

    status = await registry.dispatch(
        ".dicecmd",
        context=group_context,
    )
    assert status is not None and "关闭" in status.content

    token = QQ_SENDER_ROLE.set("owner")
    try:
        on = await registry.dispatch(
            ".dicecmd on",
            context=group_context,
        )
    finally:
        QQ_SENDER_ROLE.reset(token)
    assert on is not None and "开启" in on.content
    assert await gate.is_enabled("group-1") is True

    now_on = await registry.dispatch(
        ".dicecmd status",
        context=group_context,
    )
    assert now_on is not None and "开启" in now_on.content


@pytest.mark.asyncio
async def test_dicecmd_rejects_unknown_action(tmp_path) -> None:
    gate = DiceCategoryGate(tmp_path / "gate.sqlite3", admin_ids=["10001"])
    await gate.initialize()
    registry = CommandRegistry()
    register_dice_gate_commands(registry, gate)

    result = await registry.dispatch(
        ".dicecmd maybe",
        context=SimpleNamespace(
            conversation_id="group-1", user_id="10001"
        ),
    )
    assert result is not None
    assert "格式" in result.content


@pytest.mark.asyncio
async def test_dicecmd_requires_conversation(tmp_path) -> None:
    gate = DiceCategoryGate(tmp_path / "gate.sqlite3", admin_ids=["10001"])
    await gate.initialize()
    registry = CommandRegistry()
    register_dice_gate_commands(registry, gate)

    result = await registry.dispatch(
        ".dicecmd off",
        context=SimpleNamespace(conversation_id=None, user_id="10001"),
    )
    assert result is not None
    assert "QQ群" in result.content


# --- persistent_chat integration ---------------------------------------------


def _group_event() -> dict:
    return {
        "post_type": "message",
        "message_type": "group",
        "group_id": "group-1",
        "user_id": "10001",
        "self_id": "bot-1",
        "message": ".r 1d20",
        "raw_message": ".r 1d20",
        "sender": {"user_id": "10001", "role": "member"},
    }


def _incoming(text: str, *, conversation_id: str = "group-1") -> IncomingMessage:
    return IncomingMessage(
        platform="qq",
        message_id="msg-1",
        user_id="10001",
        user_name="测试员",
        text=text,
        conversation=ConversationContext(
            conversation_id=conversation_id,
            kind=ConversationKind.GROUP,
            name="测试群",
        ),
    )


@pytest.mark.asyncio
async def test_closed_gate_silently_consumes_dice_command(tmp_path) -> None:
    from src.chat.platform.onebot.persistent_chat import (
        handle_persistent_onebot_chat_event,
    )

    gate = DiceCategoryGate(tmp_path / "gate.sqlite3", admin_ids=["10001"])
    await gate.initialize()
    await gate.set_enabled("group-1", False, actor_user_id="10001", actor_role="owner")

    sender = AsyncMock()
    repository = AsyncMock()
    registry = CommandRegistry()
    registry.register("r", lambda _request: SimpleNamespace(content="ROLLED"), category="dice")
    incoming = _incoming(".r 1d20")

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
        handled = await handle_persistent_onebot_chat_event(
            sender,
            _group_event(),
            AsyncMock(),
            repository,
            registry,
            dice_gate=gate,
        )

    # Silently consumed: reported handled, no dice roll, no LLM turn.
    assert handled is True
    sender.send_message.assert_not_awaited()
    repository.record_incoming.assert_awaited_once()


@pytest.mark.asyncio
async def test_closed_gate_does_not_affect_private_messages(tmp_path) -> None:
    from src.chat.platform.onebot.persistent_chat import (
        handle_persistent_onebot_chat_event,
    )

    gate = DiceCategoryGate(tmp_path / "gate.sqlite3", admin_ids=["10001"])
    await gate.initialize()
    await gate.set_enabled("group-1", False, actor_user_id="10001", actor_role="owner")

    sender = AsyncMock()
    repository = AsyncMock()
    registry = CommandRegistry()
    registry.register("r", lambda _request: SimpleNamespace(content="ROLLED"), category="dice")
    incoming = IncomingMessage(
        platform="qq",
        message_id="msg-2",
        user_id="10001",
        user_name="测试员",
        text=".r 1d20",
        conversation=ConversationContext(
            conversation_id="private-1",
            kind=ConversationKind.DIRECT,
            name="私聊",
        ),
    )

    with (
        patch(
            "src.chat.platform.onebot.persistent_chat.map_onebot_message",
            return_value=incoming,
        ),
        patch(
            "src.chat.platform.onebot.persistent_chat.is_supported_message_event",
            return_value=True,
        ),
        patch(
            "src.chat.platform.onebot.persistent_chat.is_bot_addressed",
            return_value=False,
        ),
    ):
        handled = await handle_persistent_onebot_chat_event(
            sender,
            _group_event(),
            AsyncMock(),
            repository,
            registry,
            dice_gate=gate,
        )

    assert handled is True
    sender.send_message.assert_awaited_once_with(_group_event(), "ROLLED")


@pytest.mark.asyncio
async def test_closed_gate_does_not_affect_non_dice_commands(tmp_path) -> None:
    from src.chat.platform.onebot.persistent_chat import (
        handle_persistent_onebot_chat_event,
    )

    gate = DiceCategoryGate(tmp_path / "gate.sqlite3", admin_ids=["10001"])
    await gate.initialize()
    await gate.set_enabled("group-1", False, actor_user_id="10001", actor_role="owner")

    sender = AsyncMock()
    repository = AsyncMock()
    registry = CommandRegistry()
    registry.register("help", lambda _request: SimpleNamespace(content="HELP"))
    incoming = _incoming(".help")

    with (
        patch(
            "src.chat.platform.onebot.persistent_chat.map_onebot_message",
            return_value=incoming,
        ),
        patch(
            "src.chat.platform.onebot.persistent_chat.is_supported_message_event",
            return_value=True,
        ),
        patch(
            "src.chat.platform.onebot.persistent_chat.is_bot_addressed",
            return_value=False,
        ),
    ):
        handled = await handle_persistent_onebot_chat_event(
            sender,
            _group_event(),
            AsyncMock(),
            repository,
            registry,
            dice_gate=gate,
        )

    assert handled is True
    sender.send_message.assert_awaited_once_with(_group_event(), "HELP")


@pytest.mark.asyncio
async def test_closed_gate_does_not_affect_dicecmd_control(tmp_path) -> None:
    from src.chat.platform.onebot.persistent_chat import (
        handle_persistent_onebot_chat_event,
    )

    gate = DiceCategoryGate(tmp_path / "gate.sqlite3", admin_ids=["10001"])
    await gate.initialize()
    await gate.set_enabled("group-1", False, actor_user_id="10001", actor_role="owner")

    sender = AsyncMock()
    repository = AsyncMock()
    registry = CommandRegistry()
    register_dice_gate_commands(registry, gate)
    incoming = _incoming(".dicecmd on")

    group_event = _group_event()
    group_event["message"] = ".dicecmd on"
    group_event["raw_message"] = ".dicecmd on"
    group_event["sender"] = {"user_id": "10001", "role": "owner"}

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
        handled = await handle_persistent_onebot_chat_event(
            sender,
            group_event,
            AsyncMock(),
            repository,
            registry,
            dice_gate=gate,
        )

    assert handled is True
    message = sender.send_message.await_args.args[1]
    assert "开启" in message
    assert await gate.is_enabled("group-1") is True


@pytest.mark.asyncio
async def test_open_gate_still_executes_dice_command(tmp_path) -> None:
    from src.chat.platform.onebot.persistent_chat import (
        handle_persistent_onebot_chat_event,
    )

    gate = DiceCategoryGate(tmp_path / "gate.sqlite3", admin_ids=["10001"])
    await gate.initialize()

    sender = AsyncMock()
    repository = AsyncMock()
    registry = CommandRegistry()
    registry.register("r", lambda _request: SimpleNamespace(content="ROLLED"), category="dice")
    incoming = _incoming(".r 1d20")

    with (
        patch(
            "src.chat.platform.onebot.persistent_chat.map_onebot_message",
            return_value=incoming,
        ),
        patch(
            "src.chat.platform.onebot.persistent_chat.is_supported_message_event",
            return_value=True,
        ),
        patch(
            "src.chat.platform.onebot.persistent_chat.is_bot_addressed",
            return_value=False,
        ),
    ):
        handled = await handle_persistent_onebot_chat_event(
            sender,
            _group_event(),
            AsyncMock(),
            repository,
            registry,
            dice_gate=gate,
        )

    assert handled is True
    sender.send_message.assert_awaited_once_with(_group_event(), "ROLLED")


@pytest.mark.asyncio
async def test_sender_role_does_not_leak_between_events(tmp_path) -> None:
    """An owner/admin event must not leak its role into the next event."""
    from src.chat.platform.onebot.persistent_chat import (
        handle_persistent_onebot_chat_event,
    )

    gate = DiceCategoryGate(tmp_path / "gate.sqlite3", admin_ids=["10001"])
    await gate.initialize()

    repository = AsyncMock()
    registry = CommandRegistry()
    register_dice_gate_commands(registry, gate)

    # First event: the group owner toggles the gate on.
    owner_sender = AsyncMock()
    owner_event = _group_event()
    owner_event["message"] = ".dicecmd on"
    owner_event["raw_message"] = ".dicecmd on"
    owner_event["sender"] = {"user_id": "10001", "role": "owner"}
    owner_incoming = _incoming(".dicecmd on")

    with (
        patch(
            "src.chat.platform.onebot.persistent_chat.map_onebot_message",
            return_value=owner_incoming,
        ),
        patch(
            "src.chat.platform.onebot.persistent_chat.is_supported_message_event",
            return_value=True,
        ),
    ):
        handled = await handle_persistent_onebot_chat_event(
            owner_sender,
            owner_event,
            AsyncMock(),
            repository,
            registry,
            dice_gate=gate,
        )
    assert handled is True
    assert "开启" in owner_sender.send_message.await_args.args[1]

    # The role ContextVar must be fully reset after the first event.
    assert QQ_SENDER_ROLE.get() is None

    # Second event: an ordinary member must NOT inherit owner permissions.
    member_sender = AsyncMock()
    member_event = _group_event()
    member_event["message"] = ".dicecmd off"
    member_event["raw_message"] = ".dicecmd off"
    member_event["sender"] = {"user_id": "20002", "role": "member"}
    member_incoming = IncomingMessage(
        platform="qq",
        message_id="msg-2",
        user_id="20002",
        user_name="普通成员",
        text=".dicecmd off",
        conversation=ConversationContext(
            conversation_id="group-1",
            kind=ConversationKind.GROUP,
            name="测试群",
        ),
    )

    with (
        patch(
            "src.chat.platform.onebot.persistent_chat.map_onebot_message",
            return_value=member_incoming,
        ),
        patch(
            "src.chat.platform.onebot.persistent_chat.is_supported_message_event",
            return_value=True,
        ),
    ):
        handled = await handle_persistent_onebot_chat_event(
            member_sender,
            member_event,
            AsyncMock(),
            repository,
            registry,
            dice_gate=gate,
        )
    assert handled is True
    message = member_sender.send_message.await_args.args[1]
    assert "权限不足" in message
    # The gate stays on: the ordinary member could not change it.
    assert await gate.is_enabled("group-1") is True
    assert QQ_SENDER_ROLE.get() is None
