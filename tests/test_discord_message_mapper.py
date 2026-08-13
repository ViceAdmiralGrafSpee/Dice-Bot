from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import discord

from src.chat.platform import ConversationKind
from src.chat.platform.discord import map_discord_message


def _discord_message(channel, guild):
    author = Mock(spec=discord.Member)
    author.id = 10001
    author.display_name = "调查员"

    message = Mock(spec=discord.Message)
    message.id = 90009
    message.author = author
    message.channel = channel
    message.guild = guild
    message.created_at = datetime(2026, 8, 13, 12, 0, tzinfo=timezone.utc)
    message.reference = None
    return message


def test_maps_discord_channel_message_from_existing_processor_output():
    guild = Mock(spec=discord.Guild)
    guild.id = 20002
    guild.name = "TRPG Server"

    channel = Mock(spec=discord.TextChannel)
    channel.id = 30003
    channel.name = "跑团频道"

    message = _discord_message(channel, guild)
    incoming = map_discord_message(
        message,
        {
            "user_content": "骰 2d6+3",
            "replied_content": "",
            "image_data_list": [],
        },
    )

    assert incoming.platform == "discord"
    assert incoming.message_id == "90009"
    assert incoming.user_id == "10001"
    assert incoming.text == "骰 2d6+3"
    assert incoming.conversation.kind is ConversationKind.CHANNEL
    assert incoming.conversation.conversation_id == "30003"
    assert incoming.conversation.space_id == "20002"
    assert incoming.conversation.space_name == "TRPG Server"


def test_maps_thread_reply_images_and_cached_starter_message():
    guild = Mock(spec=discord.Guild)
    guild.id = 20002
    guild.name = "TRPG Server"

    owner = Mock(spec=discord.Member)
    owner.id = 10001
    owner.display_name = "调查员"

    parent = Mock(spec=discord.TextChannel)
    parent.id = 30003
    parent.name = "跑团频道"

    thread = Mock(spec=discord.Thread)
    thread.id = 40004
    thread.name = "旧宅调查"
    thread.owner = owner
    thread.owner_id = owner.id
    thread.parent = parent
    thread.parent_id = parent.id
    thread.applied_tags = [SimpleNamespace(name="COC"), SimpleNamespace(name="进行中")]
    thread.starter_message = SimpleNamespace(content="调查员收到了一封没有署名的信。")

    replied_author = Mock(spec=discord.Member)
    replied_author.id = 10002
    replied_author.display_name = "守秘人"

    message = _discord_message(thread, guild)
    message.reference = SimpleNamespace(
        message_id=80008,
        cached_message=SimpleNamespace(author=replied_author),
    )

    incoming = map_discord_message(
        message,
        {
            "user_content": "调查左边的门",
            "replied_content": "> [守秘人]:\n> 你要调查哪扇门？\n\n",
            "image_data_list": [
                {
                    "mime_type": "image/png",
                    "data": bytearray(b"image-bytes"),
                    "source": "attachment",
                    "name": "map.png",
                }
            ],
        },
    )

    assert incoming.conversation.kind is ConversationKind.THREAD
    assert incoming.conversation.thread is not None
    assert incoming.conversation.thread.owner_id == "10001"
    assert incoming.conversation.thread.parent_name == "跑团频道"
    assert incoming.conversation.thread.tags == ("COC", "进行中")
    assert incoming.conversation.thread.starter_text == "调查员收到了一封没有署名的信。"
    assert incoming.replied_message is not None
    assert incoming.replied_message.message_id == "80008"
    assert incoming.replied_message.user_name == "守秘人"
    assert incoming.replied_message.text.startswith("> [守秘人]")
    assert incoming.images[0].data == b"image-bytes"
    assert incoming.images[0].name == "map.png"
