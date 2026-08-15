import ast
from dataclasses import FrozenInstanceError
from datetime import datetime, timezone
import inspect

import pytest

import src.chat.platform.models as platform_models
from src.chat.platform import (
    ConversationContext,
    ConversationKind,
    IncomingMessage,
    MessageImage,
    RepliedMessage,
    ThreadContext,
)


def test_qq_group_message_can_be_normalized():
    message = IncomingMessage(
        platform="qq",
        message_id="987654",
        user_id="10001",
        user_name="调查员",
        text="骰 2d6+3",
        conversation=ConversationContext(
            conversation_id="20002",
            kind=ConversationKind.GROUP,
            name="周末团",
            space_id="20002",
            space_name="周末团",
        ),
        timestamp=datetime(2026, 8, 13, 12, 0, tzinfo=timezone.utc),
    )

    assert message.platform == "qq"
    assert message.conversation.kind is ConversationKind.GROUP
    assert message.conversation.conversation_id == "20002"
    assert message.text == "骰 2d6+3"
    assert message.replied_message is None
    assert message.images == ()
    assert message.files == ()


def test_discord_thread_message_keeps_required_context():
    image = MessageImage(
        mime_type="image/png",
        data=b"image-bytes",
        source="attachment",
        name="map.png",
    )
    replied_message = RepliedMessage(
        message_id="41",
        user_id="7",
        user_name="Keeper",
        text="你要调查哪扇门？",
    )
    message = IncomingMessage(
        platform="discord",
        message_id="42",
        user_id="8",
        user_name="Investigator",
        text="调查左边的门",
        conversation=ConversationContext(
            conversation_id="30003",
            kind=ConversationKind.THREAD,
            name="旧宅调查",
            space_id="40004",
            space_name="TRPG Server",
            thread=ThreadContext(
                owner_id="8",
                owner_name="Investigator",
                parent_id="50005",
                parent_name="跑团频道",
                tags=("COC", "进行中"),
                starter_text="调查员收到了一封没有署名的信。",
            ),
        ),
        replied_message=replied_message,
        images=(image,),
    )

    assert message.conversation.thread is not None
    assert message.conversation.thread.owner_id == "8"
    assert message.conversation.thread.starter_text == "调查员收到了一封没有署名的信。"
    assert message.replied_message is replied_message
    assert message.images == (image,)


def test_normalized_messages_are_immutable_values():
    message = IncomingMessage(
        platform="qq",
        message_id="1",
        user_id="2",
        user_name="Player",
        text="hello",
        conversation=ConversationContext(
            conversation_id="3",
            kind=ConversationKind.GROUP,
        ),
    )

    with pytest.raises(FrozenInstanceError):
        message.text = "changed"


def test_platform_models_do_not_import_discord():
    syntax_tree = ast.parse(inspect.getsource(platform_models))
    imported_roots = set()

    for node in ast.walk(syntax_tree):
        if isinstance(node, ast.Import):
            imported_roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_roots.add(node.module.split(".", 1)[0])

    assert "discord" not in imported_roots
