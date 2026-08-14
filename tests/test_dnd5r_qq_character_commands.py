import re
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.chat.actions import ActionContext
from src.chat.commands import CommandRegistry, CommandResult
from src.chat.platform import MessageFile
from src.chat.platform.onebot.file_transfer import RecentMessageFileStore
from src.chat.platform.onebot.persistent_chat import (
    handle_persistent_onebot_chat_event,
)
from src.chat.rules.dnd5r import (
    DND5R_CHARACTER_SCHEMA,
    Dnd5rCharacterService,
    create_dnd5r_confirmation_router,
    register_dnd5r_character_commands,
)
from src.chat.memory import SQLiteConversationRepository
from src.trpg import SQLiteTrpgRepository
from src.trpg.characters import (
    CharacterManagementService,
    CharacterServiceRegistry,
)
from src.trpg.importing import CharacterDraft, DraftField, SourceSnapshot
from src.trpg.importing.service import CharacterDraftService


def _draft() -> CharacterDraft:
    source = SourceSnapshot(
        source_type="xlsx",
        original_filename="temporary.xlsx",
        sha256="abc123",
        byte_size=10,
    )
    return CharacterDraft(
        ruleset_key="dnd5r",
        schema_version=1,
        source=source,
        template_profile_id="test.v1",
        template_confidence=1.0,
        fields={
            "identity.name": DraftField(
                path="identity.name",
                value="阿莉娅",
                sources=(),
                confidence=1.0,
                mapping_method="test",
            ),
            "progression.total_level": DraftField(
                path="progression.total_level",
                value=3,
                sources=(),
                confidence=1.0,
                mapping_method="test",
            ),
        },
    )


async def _draft_service(tmp_path) -> tuple[SQLiteTrpgRepository, CharacterDraftService]:
    repository = SQLiteTrpgRepository(tmp_path / "trpg.sqlite3")
    await repository.initialize()
    character_services = CharacterServiceRegistry()
    character_services.register(Dnd5rCharacterService(repository))
    return repository, CharacterDraftService(
        repository,
        character_services,
        {"dnd5r": DND5R_CHARACTER_SCHEMA},
    )


@pytest.mark.asyncio
async def test_pc_import_preview_and_confirmation_use_shared_actions(tmp_path) -> None:
    repository, service = await _draft_service(tmp_path)
    management_service = CharacterManagementService(repository)

    class FakeImporter:
        def inspect_and_create_draft(self, path):
            assert path.read_bytes() == b"fake-xlsx"
            return _draft()

    registry = CommandRegistry()
    register_dnd5r_character_commands(
        registry,
        service,
        character_management_service=management_service,
    )
    handler = registry._handlers["pc"]
    handler.importer = FakeImporter()
    provider = SimpleNamespace(read=AsyncMock(return_value=b"fake-xlsx"))
    context = ActionContext(
        platform="qq",
        user_id="10001",
        user_name="玩家甲",
        files=(MessageFile("file-1", "我的角色卡.xlsx", 1024),),
        file_provider=provider,
    )

    imported = await registry.dispatch(".pc import", context)

    assert imported is not None
    assert "来源：我的角色卡.xlsx" in imported.content
    match = re.search(r"角色卡导入草稿：([A-Za-z0-9_-]+)", imported.content)
    assert match is not None
    draft_id = match.group(1)
    preview = await registry.dispatch(f".pc preview {draft_id}", context)
    assert preview is not None
    assert "角色名：阿莉娅" in preview.content

    confirmation_router = create_dnd5r_confirmation_router(
        service,
        management_service,
    )
    confirmed = await confirmation_router(f"确认 {draft_id}", context)

    assert confirmed is not None
    assert "已确认并导入 dnd5r 角色卡：阿莉娅" in confirmed.content
    stored_draft = await repository.get_character_draft(draft_id)
    assert stored_draft is not None
    character = await repository.get_character(
        stored_draft.confirmed_character_id
    )
    assert character is not None
    assert character.sheet_data["import_provenance"]["draft_id"] == draft_id

    listed = await registry.dispatch(".pc list", context)
    assert listed is not None
    assert f"阿莉娅｜dnd5r｜ID：{character.character_id}" in listed.content

    prepared = await registry.dispatch(
        f".pc delete {character.character_id}",
        context,
    )
    assert prepared is not None
    assert f"确认删除 {character.character_id}" in prepared.content
    assert (await repository.get_character(character.character_id)).status == "active"

    other_user_context = ActionContext(
        platform="qq",
        user_id="another-user",
        user_name="其他玩家",
    )
    rejected = await confirmation_router(
        f"确认删除 {character.character_id}",
        other_user_context,
    )
    assert rejected is not None
    assert "找不到属于你的角色卡" in rejected.content
    assert (await repository.get_character(character.character_id)).status == "active"

    deleted = await confirmation_router(
        f"确认删除 {character.character_id}",
        context,
    )
    assert deleted is not None
    assert "角色卡已删除（可恢复）" in deleted.content
    assert (await repository.get_character(character.character_id)).status == (
        "archived"
    )
    listed_after_delete = await registry.dispatch(".pc list", context)
    assert listed_after_delete is not None
    assert listed_after_delete.content == "你还没有已导入的角色卡。"


@pytest.mark.asyncio
async def test_two_message_qq_upload_reuses_recent_file_for_same_user(
    tmp_path,
) -> None:
    memory = SQLiteConversationRepository(tmp_path / "memory.sqlite3")
    await memory.initialize()
    recent_files = RecentMessageFileStore()
    registry = CommandRegistry()
    seen_requests = []

    async def pc_handler(request):
        seen_requests.append(request)
        return CommandResult("imported")

    registry.register("pc", pc_handler)
    sender = AsyncMock()
    chat_core = SimpleNamespace(
        should_process_message=AsyncMock(),
        handle_chat_message=AsyncMock(),
    )
    provider = SimpleNamespace(read=AsyncMock())
    file_event = {
        "self_id": "90001",
        "post_type": "message",
        "message_type": "private",
        "message_id": "1",
        "user_id": "10001",
        "sender": {"nickname": "玩家甲"},
        "message": [
            {
                "type": "file",
                "data": {
                    "file": "角色卡.xlsx",
                    "file_id": "file-1",
                    "file_size": "1024",
                },
            }
        ],
    }
    command_event = {
        "self_id": "90001",
        "post_type": "message",
        "message_type": "private",
        "message_id": "2",
        "user_id": "10001",
        "sender": {"nickname": "玩家甲"},
        "message": [{"type": "text", "data": {"text": ".pc import"}}],
    }

    first_handled = await handle_persistent_onebot_chat_event(
        sender,
        file_event,
        chat_core,
        memory,
        registry,
        file_provider=provider,
        recent_files=recent_files,
    )
    second_handled = await handle_persistent_onebot_chat_event(
        sender,
        command_event,
        chat_core,
        memory,
        registry,
        file_provider=provider,
        recent_files=recent_files,
    )

    assert first_handled is True
    assert second_handled is True
    assert sender.send_message.await_args_list[0].args[1].startswith("已收到 XLSX")
    assert sender.send_message.await_args_list[1].args == (command_event, "imported")
    assert len(seen_requests) == 1
    assert seen_requests[0].context.files[0].file_id == "file-1"
    assert seen_requests[0].context.file_provider is provider
    chat_core.handle_chat_message.assert_not_awaited()
