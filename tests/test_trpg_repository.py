import pytest

from src.trpg import SQLiteTrpgRepository


async def _create_campaign(
    repository: SQLiteTrpgRepository,
    *,
    campaign_id: str,
    name: str,
    ruleset_key: str = "dnd5e",
):
    return await repository.create_campaign(
        campaign_id=campaign_id,
        name=name,
        ruleset_key=ruleset_key,
        platform="qq",
        conversation_id=f"group:{campaign_id}",
        created_by_user_id="10001",
    )


@pytest.mark.asyncio
async def test_campaign_and_character_survive_repository_restart(tmp_path) -> None:
    db_path = tmp_path / "trpg.sqlite3"
    repository = SQLiteTrpgRepository(db_path)
    await repository.initialize()
    campaign = await _create_campaign(
        repository,
        campaign_id="campaign-1",
        name="迷雾镇",
    )
    character = await repository.create_character(
        character_id="character-1",
        owner_platform="qq",
        owner_user_id="20002",
        owner_name="玩家甲",
        name="艾琳",
        ruleset_key="dnd5e",
        sheet_data={"level": 3, "abilities": {"strength": 12}},
    )
    await repository.add_character_to_campaign(
        campaign_id=campaign.campaign_id,
        character_id=character.character_id,
        alias="队长",
        state_data={"hp": 18},
    )

    reopened = SQLiteTrpgRepository(db_path)
    await reopened.initialize()

    stored_character = await reopened.get_character(character.character_id)
    membership = await reopened.get_campaign_character(
        campaign.campaign_id,
        character.character_id,
    )
    assert stored_character is not None
    assert stored_character.sheet_data == {
        "abilities": {"strength": 12},
        "level": 3,
    }
    assert membership is not None
    assert membership.alias == "队长"
    assert membership.state_data == {"hp": 18}


@pytest.mark.asyncio
async def test_one_character_can_keep_separate_state_in_multiple_campaigns(
    tmp_path,
) -> None:
    repository = SQLiteTrpgRepository(tmp_path / "trpg.sqlite3")
    await repository.initialize()
    first_campaign = await _create_campaign(
        repository,
        campaign_id="campaign-a",
        name="长期团",
    )
    second_campaign = await _create_campaign(
        repository,
        campaign_id="campaign-b",
        name="周末短团",
    )
    character = await repository.create_character(
        character_id="shared-character",
        owner_platform="qq",
        owner_user_id="20002",
        owner_name="玩家甲",
        name="艾琳",
        ruleset_key="dnd5e",
        sheet_data={"class": "fighter"},
    )

    await repository.add_character_to_campaign(
        campaign_id=first_campaign.campaign_id,
        character_id=character.character_id,
        state_data={"hp": 8},
    )
    await repository.add_character_to_campaign(
        campaign_id=second_campaign.campaign_id,
        character_id=character.character_id,
        state_data={"hp": 24},
    )

    memberships = await repository.list_campaigns_for_character(
        character.character_id
    )
    assert {membership.campaign_id for membership in memberships} == {
        first_campaign.campaign_id,
        second_campaign.campaign_id,
    }
    assert {
        membership.campaign_id: membership.state_data["hp"]
        for membership in memberships
    } == {"campaign-a": 8, "campaign-b": 24}


@pytest.mark.asyncio
async def test_campaign_memberships_are_isolated(tmp_path) -> None:
    repository = SQLiteTrpgRepository(tmp_path / "trpg.sqlite3")
    await repository.initialize()
    first_campaign = await _create_campaign(
        repository,
        campaign_id="campaign-a",
        name="A 团",
    )
    second_campaign = await _create_campaign(
        repository,
        campaign_id="campaign-b",
        name="B 团",
    )
    character = await repository.create_character(
        character_id="character-1",
        owner_platform="qq",
        owner_user_id="20002",
        owner_name="玩家甲",
        name="艾琳",
        ruleset_key="dnd5e",
    )
    await repository.add_character_to_campaign(
        campaign_id=first_campaign.campaign_id,
        character_id=character.character_id,
    )

    assert len(
        await repository.list_characters_for_campaign(first_campaign.campaign_id)
    ) == 1
    assert (
        await repository.list_characters_for_campaign(second_campaign.campaign_id)
        == []
    )


@pytest.mark.asyncio
async def test_character_cannot_join_campaign_from_another_ruleset(tmp_path) -> None:
    repository = SQLiteTrpgRepository(tmp_path / "trpg.sqlite3")
    await repository.initialize()
    campaign = await _create_campaign(
        repository,
        campaign_id="coc-campaign",
        name="调查团",
        ruleset_key="coc7",
    )
    character = await repository.create_character(
        character_id="dnd-character",
        owner_platform="qq",
        owner_user_id="20002",
        owner_name="玩家甲",
        name="艾琳",
        ruleset_key="dnd5e",
    )

    with pytest.raises(ValueError, match="规则系统不一致"):
        await repository.add_character_to_campaign(
            campaign_id=campaign.campaign_id,
            character_id=character.character_id,
        )


@pytest.mark.asyncio
async def test_repeated_initialize_does_not_erase_data(tmp_path) -> None:
    repository = SQLiteTrpgRepository(tmp_path / "trpg.sqlite3")
    await repository.initialize()
    campaign = await _create_campaign(
        repository,
        campaign_id="campaign-1",
        name="不会被清空的团",
    )

    await repository.initialize()

    assert await repository.get_campaign(campaign.campaign_id) == campaign
