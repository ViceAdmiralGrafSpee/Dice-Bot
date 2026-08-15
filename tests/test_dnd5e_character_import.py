from dataclasses import dataclass

import pytest

from src.chat.actions import (
    ActionContext,
    ImportCharacterAction,
    ImportCharacterRequest,
)
from src.chat.rules.dnd5e import Dnd5eCharacterService
from src.trpg import SQLiteTrpgRepository
from src.trpg.characters import (
    CharacterImportData,
    CharacterServiceNotFoundError,
    CharacterServiceRegistry,
)


@pytest.mark.asyncio
async def test_registry_routes_import_to_matching_ruleset_service() -> None:
    calls = []

    @dataclass
    class RecordingService:
        ruleset_key: str = "dnd5e"

        async def import_character(self, request):
            calls.append(request)
            return "routed"

    registry = CharacterServiceRegistry()
    registry.register(RecordingService())
    request = CharacterImportData(
        owner_platform="qq",
        owner_user_id="10001",
        owner_name="玩家",
        sheet_data={"name": "艾琳"},
    )

    result = await registry.import_character("DND5E", request)

    assert result == "routed"
    assert calls == [request]


@pytest.mark.asyncio
async def test_dnd5e_import_action_validates_and_persists_character(tmp_path) -> None:
    repository = SQLiteTrpgRepository(tmp_path / "trpg.sqlite3")
    await repository.initialize()
    services = CharacterServiceRegistry()
    services.register(Dnd5eCharacterService(repository))
    action = ImportCharacterAction(services)

    result = await action.execute(
        ImportCharacterRequest(
            ruleset_key="dnd5e",
            character_id="character-1",
            sheet_data={
                "name": "  艾琳  ",
                "level": 3,
                "class": "fighter",
                "ability_scores": {"strength": 16},
            },
        ),
        ActionContext(
            platform="qq",
            user_id="10001",
            user_name="玩家甲",
        ),
    )

    stored = await repository.get_character("character-1")
    assert stored is not None
    assert stored.owner_platform == "qq"
    assert stored.owner_user_id == "10001"
    assert stored.name == "艾琳"
    assert stored.ruleset_key == "dnd5e"
    assert stored.sheet_version == 1
    assert stored.sheet_data == {
        "ability_scores": {"strength": 16},
        "class": "fighter",
        "edition": "2014",
        "level": 3,
        "name": "艾琳",
    }
    assert result.data == {
        "character_id": "character-1",
        "ruleset": "dnd5e",
        "name": "艾琳",
        "sheet_version": 1,
    }
    assert result.authoritative_output == (
        "已导入 dnd5e 角色卡：艾琳（ID：character-1）"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("sheet_data", "error"),
    [
        ({"level": 3}, "缺少有效的 name"),
        ({"name": "艾琳", "edition": "2024"}, "只接受 D&D 5e 2014"),
        ({"name": "艾琳", "level": 0}, "level 必须是 1 到 20"),
    ],
)
async def test_invalid_dnd5e_sheet_is_not_saved(
    tmp_path,
    sheet_data,
    error,
) -> None:
    repository = SQLiteTrpgRepository(tmp_path / "trpg.sqlite3")
    await repository.initialize()
    services = CharacterServiceRegistry()
    services.register(Dnd5eCharacterService(repository))
    action = ImportCharacterAction(services)

    with pytest.raises(ValueError, match=error):
        await action.execute(
            ImportCharacterRequest(
                ruleset_key="dnd5e",
                character_id="invalid-character",
                sheet_data=sheet_data,
            ),
            ActionContext(platform="qq", user_id="10001"),
        )

    assert await repository.get_character("invalid-character") is None


@pytest.mark.asyncio
async def test_unknown_ruleset_is_rejected_before_database_write(tmp_path) -> None:
    repository = SQLiteTrpgRepository(tmp_path / "trpg.sqlite3")
    await repository.initialize()
    action = ImportCharacterAction(CharacterServiceRegistry())

    with pytest.raises(CharacterServiceNotFoundError, match="尚未支持"):
        await action.execute(
            ImportCharacterRequest(
                ruleset_key="coc7",
                character_id="character-1",
                sheet_data={"name": "调查员"},
            ),
            ActionContext(platform="qq", user_id="10001"),
        )

    assert await repository.get_character("character-1") is None
