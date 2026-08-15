"""Tests for OneBot-layer @ targeting and the per-group require-at policy.

Covers ``analyze_at_targeting``, ``strip_at_mentions``, the SQLite-backed
``RequireAtPolicy`` persistence, the ``.cmdat on/off/status`` control command,
and the routing order in ``handle_persistent_onebot_chat_event``:

1. explicit @ targeting in QQ groups
2. require-at for traditional point commands
3. ``.cmdat`` permission reuse (same rule as ``.dicecmd``)
4. ``.cmdat`` obeying targeting itself
5. ordering with the dice category gate
6. no ContextVar / targeting state leaking between events
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from src.chat.commands import CommandRegistry
from src.chat.dice.gate import (
    DiceCategoryGate,
    QQ_SENDER_ROLE,
    register_dice_gate_commands,
)
from src.chat.platform import ConversationContext, ConversationKind, IncomingMessage
from src.chat.platform.onebot.command_policy import (
    RequireAtPolicy,
    analyze_at_targeting,
    register_cmdat_command,
    strip_at_mentions,
)

BOT_ID = "bot-1"
OTHER_ID = "123456"
GROUP_ID = "group-1"
USER_ID = "10001"
ADMIN_IDS = ["10001"]


# --- Event / incoming helpers -----------------------------------------------


def _group_event(
    *,
    text: str = ".r1d6",
    segments: list[dict] | None = None,
    self_id: str = BOT_ID,
    user_id: str = USER_ID,
    role: str = "member",
) -> dict:
    if segments is None:
        segments = [{"type": "text", "data": {"text": text}}]
    return {
        "post_type": "message",
        "message_type": "group",
        "group_id": GROUP_ID,
        "user_id": user_id,
        "self_id": self_id,
        "message": segments,
        "raw_message": text,
        "sender": {"user_id": user_id, "role": role},
    }


def _private_event(*, text: str = ".r1d6", self_id: str = BOT_ID) -> dict:
    return {
        "post_type": "message",
        "message_type": "private",
        "user_id": USER_ID,
        "self_id": self_id,
        "message": [{"type": "text", "data": {"text": text}}],
        "raw_message": text,
        "sender": {"user_id": USER_ID},
    }


def _incoming(
    text: str,
    *,
    conversation_id: str = GROUP_ID,
    kind: ConversationKind = ConversationKind.GROUP,
) -> IncomingMessage:
    return IncomingMessage(
        platform="qq",
        message_id="msg-1",
        user_id=USER_ID,
        user_name="测试员",
        text=text,
        conversation=ConversationContext(
            conversation_id=conversation_id,
            kind=kind,
            name="测试群" if kind is ConversationKind.GROUP else "私聊",
        ),
    )


def _self_at_event(*, text: str = ".r1d6") -> dict:
    """Event whose segments are ``@bot-1 <text>`` (mapper drops our own @)."""
    return _group_event(
        text=text,
        segments=[
            {"type": "at", "data": {"qq": BOT_ID}},
            {"type": "text", "data": {"text": text}},
        ],
    )


def _other_at_event(*, text: str = ".r1d6") -> dict:
    """Event whose segments are ``@123456 <text>`` (mapper keeps @123456)."""
    return _group_event(
        text=f"[CQ:at,qq={OTHER_ID}]{text}",
        segments=[
            {"type": "at", "data": {"qq": OTHER_ID}},
            {"type": "text", "data": {"text": text}},
        ],
    )


def _mixed_at_event(*, text: str = ".r1d6") -> dict:
    """Event segments ``@123456 @bot-1 <text>``: other bot first, then us."""
    return _group_event(
        text=f"[CQ:at,qq={OTHER_ID}][CQ:at,qq={BOT_ID}]{text}",
        segments=[
            {"type": "at", "data": {"qq": OTHER_ID}},
            {"type": "at", "data": {"qq": BOT_ID}},
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


def _dice_registry() -> CommandRegistry:
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
    return registry


# --- Pure targeting helpers -------------------------------------------------


@pytest.mark.parametrize(
    ("event", "has_any_at", "includes_self"),
    [
        (_group_event(text=".r1d6"), False, False),
        (_self_at_event(), True, True),
        (_other_at_event(), True, False),
        (_mixed_at_event(), True, True),
        (
            _group_event(
                text="@全体成员 .roll 2d6",
                segments=[
                    {"type": "at", "data": {"qq": "all"}},
                    {"type": "text", "data": {"text": ".roll 2d6"}},
                ],
            ),
            True,
            False,
        ),
        (
            {
                "post_type": "message",
                "message_type": "group",
                "group_id": GROUP_ID,
                "user_id": USER_ID,
                "self_id": "different-bot",
                "message": [{"type": "at", "data": {"qq": BOT_ID}}],
                "raw_message": "[CQ:at,qq=bot-1]",
                "sender": {"user_id": USER_ID, "role": "member"},
            },
            True,
            False,
        ),
    ],
)
def test_analyze_at_targeting_uses_real_self_id(
    event: dict, has_any_at: bool, includes_self: bool
) -> None:
    result = analyze_at_targeting(event)
    assert result.has_any_at is has_any_at
    assert result.includes_self is includes_self


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (".r1d6", ".r1d6"),
        ("@123456.r1d6", ".r1d6"),
        ("@123456 .r1d6", ".r1d6"),
        ("@123456@456789.cmdat off", ".cmdat off"),
        ("@全体成员.r1d6", ".r1d6"),
        ("@另一个Bot .dnd5e 攻击", ".dnd5e 攻击"),
    ],
)
def test_strip_at_mentions(text: str, expected: str) -> None:
    assert strip_at_mentions(text) == expected
    # Strip is idempotent and leaves plain commands untouched.
    assert strip_at_mentions(expected) == expected


# --- RequireAtPolicy persistence ---------------------------------------------


@pytest.mark.asyncio
async def test_require_at_defaults_to_false(tmp_path) -> None:
    policy = RequireAtPolicy(tmp_path / "require_at.sqlite3")
    await policy.initialize()

    assert await policy.is_required(GROUP_ID) is False
    assert await policy.is_required(None) is False


@pytest.mark.asyncio
async def test_require_at_persists_across_instances(tmp_path) -> None:
    path = tmp_path / "require_at.sqlite3"

    policy = RequireAtPolicy(path, admin_ids=ADMIN_IDS)
    await policy.initialize()
    permitted, _message = await policy.set_required(
        GROUP_ID,
        True,
        actor_user_id=USER_ID,
        actor_role="owner",
    )
    assert permitted is True
    assert await policy.is_required(GROUP_ID) is True

    reopened = RequireAtPolicy(path, admin_ids=ADMIN_IDS)
    await reopened.initialize()
    assert await reopened.is_required(GROUP_ID) is True
    # Other groups and private (None) keep the default.
    assert await reopened.is_required("group-2") is False
    assert await reopened.is_required(None) is False


# --- .cmdat control command --------------------------------------------------


def _group_context(user_id: str = USER_ID) -> SimpleNamespace:
    return SimpleNamespace(conversation_id=GROUP_ID, user_id=user_id)


@pytest.mark.asyncio
async def test_cmdat_status_visible_to_everyone(tmp_path) -> None:
    policy = RequireAtPolicy(tmp_path / "require_at.sqlite3", admin_ids=ADMIN_IDS)
    await policy.initialize()
    registry = CommandRegistry()
    register_cmdat_command(registry, policy)

    off = await registry.dispatch(".cmdat status", context=_group_context("20002"))
    assert off is not None and "不要求 @机器人" in off.content

    await policy.set_required(
        GROUP_ID, True, actor_user_id=USER_ID, actor_role="owner"
    )
    on = await registry.dispatch(".cmdat status", context=_group_context("20002"))
    assert on is not None and "需要 @机器人" in on.content


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("role", "user_id"),
    [
        ("owner", USER_ID),
        ("admin", "20002"),
        ("群主", "20002"),
        ("member", USER_ID),  # QQ_BOT_ADMIN_IDS member
    ],
)
async def test_cmdat_on_off_allowed_for_managers(
    tmp_path, role: str, user_id: str
) -> None:
    policy = RequireAtPolicy(tmp_path / "require_at.sqlite3", admin_ids=ADMIN_IDS)
    await policy.initialize()
    registry = CommandRegistry()
    register_cmdat_command(registry, policy)
    context = _group_context(user_id)

    token = QQ_SENDER_ROLE.set(role)
    try:
        on = await registry.dispatch(".cmdat on", context=context)
        off = await registry.dispatch(".cmdat off", context=context)
    finally:
        QQ_SENDER_ROLE.reset(token)

    assert on is not None and "已开启" in on.content
    assert off is not None and "已关闭" in off.content
    assert await policy.is_required(GROUP_ID) is False


@pytest.mark.asyncio
async def test_cmdat_denied_for_ordinary_member(tmp_path) -> None:
    policy = RequireAtPolicy(tmp_path / "require_at.sqlite3", admin_ids=ADMIN_IDS)
    await policy.initialize()
    registry = CommandRegistry()
    register_cmdat_command(registry, policy)

    token = QQ_SENDER_ROLE.set("member")
    try:
        off = await registry.dispatch(
            ".cmdat off", context=_group_context("20002")
        )
    finally:
        QQ_SENDER_ROLE.reset(token)

    assert off is not None and "权限不足" in off.content
    # The switch is unchanged (still the default False).
    assert await policy.is_required(GROUP_ID) is False


@pytest.mark.asyncio
async def test_cmdat_requires_group_conversation(tmp_path) -> None:
    policy = RequireAtPolicy(tmp_path / "require_at.sqlite3", admin_ids=ADMIN_IDS)
    await policy.initialize()
    registry = CommandRegistry()
    register_cmdat_command(registry, policy)

    result = await registry.dispatch(
        ".cmdat on",
        context=SimpleNamespace(conversation_id=None, user_id=USER_ID),
    )
    assert result is not None and "QQ群" in result.content


@pytest.mark.asyncio
async def test_cmdat_rejects_unknown_action(tmp_path) -> None:
    policy = RequireAtPolicy(tmp_path / "require_at.sqlite3", admin_ids=ADMIN_IDS)
    await policy.initialize()
    registry = CommandRegistry()
    register_cmdat_command(registry, policy)

    result = await registry.dispatch(
        ".cmdat maybe", context=_group_context()
    )
    assert result is not None and "格式" in result.content


# --- handle_persistent_onebot_chat_event integration -------------------------


@pytest.mark.asyncio
async def test_no_at_no_require_run_command(tmp_path) -> None:
    policy = RequireAtPolicy(tmp_path / "require_at.sqlite3", admin_ids=ADMIN_IDS)
    await policy.initialize()
    registry = _dice_registry()

    sender, handled = await _handle(
        _group_event(), _incoming(".r1d6"), policy, registry
    )
    assert handled is True
    sender.send_message.assert_awaited_once_with(
        _group_event(), "ROLLED"
    )


@pytest.mark.asyncio
async def test_self_at_runs_command(tmp_path) -> None:
    policy = RequireAtPolicy(tmp_path / "require_at.sqlite3", admin_ids=ADMIN_IDS)
    await policy.initialize()
    registry = _dice_registry()

    event = _self_at_event()
    sender, handled = await _handle(event, _incoming(".r1d6"), policy, registry)
    assert handled is True
    sender.send_message.assert_awaited_once_with(event, "ROLLED")


@pytest.mark.asyncio
async def test_other_at_is_ignored(tmp_path) -> None:
    policy = RequireAtPolicy(tmp_path / "require_at.sqlite3", admin_ids=ADMIN_IDS)
    await policy.initialize()
    registry = _dice_registry()

    sender, handled = await _handle(
        _other_at_event(), _incoming("@123456.r1d6"), policy, registry
    )
    assert handled is True
    sender.send_message.assert_not_awaited()
    # The role ContextVar must never be set for a foreign mention.
    assert QQ_SENDER_ROLE.get() is None


@pytest.mark.asyncio
async def test_require_at_silently_drops_bare_command(tmp_path) -> None:
    policy = RequireAtPolicy(tmp_path / "require_at.sqlite3", admin_ids=ADMIN_IDS)
    await policy.initialize()
    await policy.set_required(
        GROUP_ID, True, actor_user_id=USER_ID, actor_role="owner"
    )
    registry = _dice_registry()

    sender, handled = await _handle(
        _group_event(), _incoming(".r1d6"), policy, registry
    )
    assert handled is True
    sender.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_require_at_allows_self_at(tmp_path) -> None:
    policy = RequireAtPolicy(tmp_path / "require_at.sqlite3", admin_ids=ADMIN_IDS)
    await policy.initialize()
    await policy.set_required(
        GROUP_ID, True, actor_user_id=USER_ID, actor_role="owner"
    )
    registry = _dice_registry()

    event = _self_at_event()
    sender, handled = await _handle(event, _incoming(".r1d6"), policy, registry)
    assert handled is True
    sender.send_message.assert_awaited_once_with(event, "ROLLED")


@pytest.mark.asyncio
async def test_require_at_ignores_other_at(tmp_path) -> None:
    policy = RequireAtPolicy(tmp_path / "require_at.sqlite3", admin_ids=ADMIN_IDS)
    await policy.initialize()
    await policy.set_required(
        GROUP_ID, True, actor_user_id=USER_ID, actor_role="owner"
    )
    registry = _dice_registry()

    sender, handled = await _handle(
        _other_at_event(), _incoming("@123456.r1d6"), policy, registry
    )
    assert handled is True
    sender.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_require_at_allows_dnd5e_to_reach_dnd_command(tmp_path) -> None:
    policy = RequireAtPolicy(tmp_path / "require_at.sqlite3", admin_ids=ADMIN_IDS)
    await policy.initialize()
    await policy.set_required(
        GROUP_ID, True, actor_user_id=USER_ID, actor_role="owner"
    )
    registry = _dice_registry()

    event = _self_at_event(text=".dnd5e 攻击检定")
    sender, handled = await _handle(
        event, _incoming(".dnd5e 攻击检定"), policy, registry
    )
    assert handled is True
    sender.send_message.assert_awaited_once_with(event, "DND")


@pytest.mark.asyncio
async def test_private_message_ignores_require_at(tmp_path) -> None:
    policy = RequireAtPolicy(tmp_path / "require_at.sqlite3", admin_ids=ADMIN_IDS)
    await policy.initialize()
    await policy.set_required(
        GROUP_ID, True, actor_user_id=USER_ID, actor_role="owner"
    )
    registry = _dice_registry()

    event = _private_event()
    sender, handled = await _handle(
        event,
        _incoming(
            ".r1d6",
            conversation_id=USER_ID,
            kind=ConversationKind.DIRECT,
        ),
        policy,
        registry,
    )
    assert handled is True
    sender.send_message.assert_awaited_once_with(event, "ROLLED")


@pytest.mark.asyncio
async def test_bare_cmdat_off_silently_dropped_when_required(tmp_path) -> None:
    policy = RequireAtPolicy(tmp_path / "require_at.sqlite3", admin_ids=ADMIN_IDS)
    await policy.initialize()
    await policy.set_required(
        GROUP_ID, True, actor_user_id=USER_ID, actor_role="owner"
    )
    registry = CommandRegistry()
    register_cmdat_command(registry, policy)

    sender, handled = await _handle(
        _group_event(text=".cmdat off"),
        _incoming(".cmdat off"),
        policy,
        registry,
    )
    assert handled is True
    sender.send_message.assert_not_awaited()
    # The policy must remain enabled.
    assert await policy.is_required(GROUP_ID) is True


@pytest.mark.asyncio
async def test_self_cmdat_off_disables_require_at(tmp_path) -> None:
    policy = RequireAtPolicy(tmp_path / "require_at.sqlite3", admin_ids=ADMIN_IDS)
    await policy.initialize()
    await policy.set_required(
        GROUP_ID, True, actor_user_id=USER_ID, actor_role="owner"
    )
    registry = CommandRegistry()
    register_cmdat_command(registry, policy)

    event = _self_at_event(text=".cmdat off")
    event["sender"] = {"user_id": USER_ID, "role": "owner"}
    sender, handled = await _handle(
        event, _incoming(".cmdat off"), policy, registry
    )
    assert handled is True
    message = sender.send_message.await_args.args[1]
    assert "已关闭" in message
    assert await policy.is_required(GROUP_ID) is False


@pytest.mark.asyncio
async def test_other_cmdat_never_executes(tmp_path) -> None:
    policy = RequireAtPolicy(tmp_path / "require_at.sqlite3", admin_ids=ADMIN_IDS)
    await policy.initialize()
    registry = CommandRegistry()
    register_cmdat_command(registry, policy)

    sender, handled = await _handle(
        _other_at_event(text=".cmdat off"),
        _incoming("@123456.cmdat off"),
        policy,
        registry,
    )
    assert handled is True
    sender.send_message.assert_not_awaited()
    assert await policy.is_required(GROUP_ID) is False


@pytest.mark.asyncio
async def test_require_at_silently_consumes_dicecmd_off(tmp_path) -> None:
    policy = RequireAtPolicy(tmp_path / "require_at.sqlite3", admin_ids=ADMIN_IDS)
    await policy.initialize()
    await policy.set_required(
        GROUP_ID, True, actor_user_id=USER_ID, actor_role="owner"
    )
    gate = DiceCategoryGate(tmp_path / "gate.sqlite3", admin_ids=ADMIN_IDS)
    await gate.initialize()
    registry = CommandRegistry()
    register_dice_gate_commands(registry, gate)
    register_cmdat_command(registry, policy)
    registry.register(
        "r", lambda _request: SimpleNamespace(content="ROLLED"), category="dice"
    )

    # Bare .dicecmd off is dropped while require-at is on.
    sender, handled = await _handle(
        _group_event(text=".dicecmd off"),
        _incoming(".dicecmd off"),
        policy,
        registry,
        dice_gate=gate,
    )
    assert handled is True
    sender.send_message.assert_not_awaited()
    assert await gate.is_enabled(GROUP_ID) is True

    # @self .dicecmd off still works and changes this bot's own group switch.
    event = _self_at_event(text=".dicecmd off")
    event["sender"] = {"user_id": USER_ID, "role": "owner"}
    sender, handled = await _handle(
        event, _incoming(".dicecmd off"), policy, registry, dice_gate=gate
    )
    assert handled is True
    message = sender.send_message.await_args.args[1]
    assert "关闭" in message
    assert await gate.is_enabled(GROUP_ID) is False


@pytest.mark.asyncio
async def test_dice_gate_still_blocks_self_at_roll_when_closed(tmp_path) -> None:
    policy = RequireAtPolicy(tmp_path / "require_at.sqlite3", admin_ids=ADMIN_IDS)
    await policy.initialize()
    await policy.set_required(
        GROUP_ID, True, actor_user_id=USER_ID, actor_role="owner"
    )
    gate = DiceCategoryGate(tmp_path / "gate.sqlite3", admin_ids=ADMIN_IDS)
    await gate.initialize()
    await gate.set_enabled(GROUP_ID, False, actor_user_id=USER_ID, actor_role="owner")
    registry = _dice_registry()

    event = _self_at_event()
    sender, handled = await _handle(
        event, _incoming(".r1d6"), policy, registry, dice_gate=gate
    )
    assert handled is True
    sender.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_mixed_at_including_self_runs_command(tmp_path) -> None:
    policy = RequireAtPolicy(tmp_path / "require_at.sqlite3", admin_ids=ADMIN_IDS)
    await policy.initialize()
    registry = _dice_registry()

    event = _mixed_at_event()
    sender, handled = await _handle(
        event, _incoming("@123456.r1d6"), policy, registry
    )
    assert handled is True
    # The stripped text ".r1d6" dispatches; the @123456 prefix never reaches
    # the registry.
    sender.send_message.assert_awaited_once_with(event, "ROLLED")


@pytest.mark.asyncio
async def test_targeting_state_does_not_leak_between_events(tmp_path) -> None:
    """No @-targeting / role state may leak from one event into the next."""
    policy = RequireAtPolicy(tmp_path / "require_at.sqlite3", admin_ids=ADMIN_IDS)
    await policy.initialize()
    registry = CommandRegistry()
    register_cmdat_command(registry, policy)
    registry.register(
        "r", lambda _request: SimpleNamespace(content="ROLLED"), category="dice"
    )

    # First event: the owner uses @self .cmdat on (the role ContextVar is set).
    first_event = _self_at_event(text=".cmdat on")
    first_event["sender"] = {"user_id": USER_ID, "role": "owner"}
    sender, handled = await _handle(
        first_event, _incoming(".cmdat on"), policy, registry
    )
    assert handled is True
    assert "已开启" in sender.send_message.await_args.args[1]
    assert QQ_SENDER_ROLE.get() is None
    assert analyze_at_targeting(_group_event()).includes_self is False

    # Second event: the policy is now on, so a bare .r1d6 must be silently
    # dropped as if it were the very first event.
    second_sender, handled = await _handle(
        _group_event(), _incoming(".r1d6"), policy, registry
    )
    assert handled is True
    second_sender.send_message.assert_not_awaited()
    assert QQ_SENDER_ROLE.get() is None