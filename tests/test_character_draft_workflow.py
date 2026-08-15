import aiosqlite
import pytest

from src.chat.actions import (
    ActionContext,
    ConfirmCharacterDraftAction,
    ConfirmCharacterDraftRequest,
    PreviewCharacterDraftAction,
    PreviewCharacterDraftRequest,
    SaveCharacterDraftAction,
    SaveCharacterDraftRequest,
)
from src.chat.rules.dnd5r import (
    DND5R_CHARACTER_SCHEMA,
    Dnd5rCharacterService,
)
from src.trpg import SQLiteTrpgRepository
from src.trpg.characters import CharacterServiceRegistry
from src.trpg.importing import (
    CharacterDraft,
    CharacterDraftStatus,
    DraftField,
    InspectedCell,
    InspectedSheet,
    SourceReference,
    SourceSnapshot,
    ValidationIssue,
    ValidationSeverity,
    WorkbookInspection,
)
from src.trpg.importing.service import (
    CharacterDraftOwnershipError,
    CharacterDraftService,
    CharacterDraftValidationError,
)


def _make_draft(
    *issues: ValidationIssue,
) -> CharacterDraft:
    source = SourceSnapshot(
        source_type="xlsx",
        original_filename="角色卡.xlsx",
        sha256="abc123",
        byte_size=1024,
    )
    source_reference = SourceReference(
        source_sha256=source.sha256,
        sheet="主要",
        coordinate="E3",
        original_value="阿莉娅",
    )
    inspection = WorkbookInspection(
        source=source,
        sheets=(
            InspectedSheet(
                name="主要",
                state="visible",
                cells=(
                    InspectedCell(
                        sheet="主要",
                        coordinate="E3",
                        value="阿莉娅",
                    ),
                ),
                merged_ranges=("A1:Z1",),
                max_row=3,
                max_column=26,
            ),
        ),
        diagnostics=("保留的检查信息",),
    )
    values = {
        "identity.name": "阿莉娅",
        "identity.species": "人类",
        "progression.primary_class": "战士",
        "progression.total_level": 3,
        "abilities.strength": 16,
        "combat.hit_points.maximum": 24,
        "combat.armor_class": 17,
    }
    return CharacterDraft(
        ruleset_key="dnd5r",
        schema_version=1,
        source=source,
        template_profile_id="dnd5r.test.v1",
        template_confidence=1.0,
        inspection=inspection,
        fields={
            path: DraftField(
                path=path,
                value=value,
                sources=(source_reference,),
                confidence=1.0,
                mapping_method="test",
            )
            for path, value in values.items()
        },
        extensions={"homebrew_note": "保留，不参与规则计算"},
        unmapped_regions=("附注!used-range(10x4)",),
        validation=tuple(issues),
    )


async def _create_service(tmp_path):
    repository = SQLiteTrpgRepository(tmp_path / "trpg.sqlite3")
    await repository.initialize()
    character_services = CharacterServiceRegistry()
    character_services.register(Dnd5rCharacterService(repository))
    service = CharacterDraftService(
        repository=repository,
        character_services=character_services,
        schemas={"dnd5r": DND5R_CHARACTER_SCHEMA},
    )
    return repository, service


CONTEXT = ActionContext(platform="qq", user_id="10001", user_name="玩家甲")


@pytest.mark.asyncio
async def test_draft_preview_survives_repository_restart(tmp_path) -> None:
    repository, service = await _create_service(tmp_path)
    save_action = SaveCharacterDraftAction(service)

    saved = await save_action.execute(
        SaveCharacterDraftRequest(_make_draft(), draft_id="draft-1"),
        CONTEXT,
    )

    assert saved.data == {
        "draft_id": "draft-1",
        "ruleset": "dnd5r",
        "status": "pending",
        "errors": 0,
        "warnings": 0,
    }
    assert "角色卡导入草稿：draft-1" in saved.authoritative_output
    assert "角色名：阿莉娅" in saved.authoritative_output
    assert "确认前不会写入正式角色库" in saved.authoritative_output
    assert "确认 draft-1" in saved.authoritative_output

    reopened_repository = SQLiteTrpgRepository(repository.db_path)
    await reopened_repository.initialize()
    reopened_services = CharacterServiceRegistry()
    reopened_services.register(Dnd5rCharacterService(reopened_repository))
    reopened = CharacterDraftService(
        repository=reopened_repository,
        character_services=reopened_services,
        schemas={"dnd5r": DND5R_CHARACTER_SCHEMA},
    )
    preview = await PreviewCharacterDraftAction(reopened).execute(
        PreviewCharacterDraftRequest("draft-1"),
        CONTEXT,
    )
    stored = await reopened_repository.get_character_draft("draft-1")

    assert preview.data["status"] == "pending"
    assert stored is not None
    assert stored.draft.inspection is not None
    assert stored.draft.inspection.sheets[0].merged_ranges == ("A1:Z1",)
    assert stored.draft.inspection.diagnostics == ("保留的检查信息",)
    async with aiosqlite.connect(repository.db_path) as database:
        cursor = await database.execute(
            "SELECT MAX(version) FROM trpg_schema_migrations"
        )
        row = await cursor.fetchone()
    assert row[0] == 2


@pytest.mark.asyncio
async def test_confirmation_is_atomic_and_idempotent(tmp_path) -> None:
    repository, service = await _create_service(tmp_path)
    await SaveCharacterDraftAction(service).execute(
        SaveCharacterDraftRequest(_make_draft(), draft_id="draft-1"),
        CONTEXT,
    )
    confirm_action = ConfirmCharacterDraftAction(service)

    first = await confirm_action.execute(
        ConfirmCharacterDraftRequest(
            "draft-1",
            "确认 draft-1",
            character_id="character-1",
        ),
        CONTEXT,
    )
    repeated = await confirm_action.execute(
        ConfirmCharacterDraftRequest(
            "draft-1",
            "确认 draft-1",
            character_id="must-not-be-created",
        ),
        CONTEXT,
    )

    assert first.data["character_id"] == "character-1"
    assert repeated.data["character_id"] == "character-1"
    assert await repository.get_character("must-not-be-created") is None
    character = await repository.get_character("character-1")
    assert character is not None
    assert character.name == "阿莉娅"
    assert character.ruleset_key == "dnd5r"
    assert character.sheet_data["edition"] == "2024"
    assert character.sheet_data["identity"] == {
        "name": "阿莉娅",
        "species": "人类",
    }
    assert character.sheet_data["progression"] == {
        "primary_class": "战士",
        "total_level": 3,
    }
    assert character.sheet_data["extensions"]["homebrew_note"].startswith(
        "保留"
    )
    assert (
        character.sheet_data["import_provenance"]["source"][
            "original_filename"
        ]
        == "角色卡.xlsx"
    )
    assert character.sheet_data["import_provenance"]["draft_id"] == "draft-1"
    stored = await repository.get_character_draft("draft-1")
    assert stored is not None
    assert stored.status is CharacterDraftStatus.CONFIRMED
    assert stored.confirmed_character_id == "character-1"
    assert stored.confirmed_at is not None


@pytest.mark.asyncio
async def test_error_blocks_confirmation_but_warning_does_not(tmp_path) -> None:
    repository, service = await _create_service(tmp_path)
    error = ValidationIssue(
        ValidationSeverity.ERROR,
        "INVALID_INTEGER",
        "力量无法转换为整数",
        "abilities.strength",
    )
    warning = ValidationIssue(
        ValidationSeverity.WARNING,
        "OUTSIDE_RECOMMENDED_RANGE",
        "属性值异常但允许保留",
        "abilities.strength",
    )
    save_action = SaveCharacterDraftAction(service)
    await save_action.execute(
        SaveCharacterDraftRequest(_make_draft(error), draft_id="error-draft"),
        CONTEXT,
    )
    await save_action.execute(
        SaveCharacterDraftRequest(
            _make_draft(warning),
            draft_id="warning-draft",
        ),
        CONTEXT,
    )

    with pytest.raises(CharacterDraftValidationError, match="1 个 ERROR"):
        await ConfirmCharacterDraftAction(service).execute(
            ConfirmCharacterDraftRequest(
                "error-draft",
                "确认 error-draft",
            ),
            CONTEXT,
        )

    error_record = await repository.get_character_draft("error-draft")
    assert error_record is not None
    assert error_record.status is CharacterDraftStatus.PENDING
    confirmed_warning = await ConfirmCharacterDraftAction(service).execute(
        ConfirmCharacterDraftRequest(
            "warning-draft",
            "确认 warning-draft",
            character_id="warning-character",
        ),
        CONTEXT,
    )
    assert confirmed_warning.data["character_id"] == "warning-character"


@pytest.mark.asyncio
async def test_other_user_cannot_preview_or_confirm_draft(tmp_path) -> None:
    _, service = await _create_service(tmp_path)
    await SaveCharacterDraftAction(service).execute(
        SaveCharacterDraftRequest(_make_draft(), draft_id="private-draft"),
        CONTEXT,
    )
    other_user = ActionContext(
        platform="qq",
        user_id="20002",
        user_name="其他玩家",
    )

    with pytest.raises(CharacterDraftOwnershipError):
        await PreviewCharacterDraftAction(service).execute(
            PreviewCharacterDraftRequest("private-draft"),
            other_user,
        )
    with pytest.raises(CharacterDraftOwnershipError):
        await ConfirmCharacterDraftAction(service).execute(
            ConfirmCharacterDraftRequest(
                "private-draft",
                "确认 private-draft",
            ),
            other_user,
        )


@pytest.mark.asyncio
async def test_confirmation_requires_exact_user_phrase(tmp_path) -> None:
    repository, service = await _create_service(tmp_path)
    await SaveCharacterDraftAction(service).execute(
        SaveCharacterDraftRequest(_make_draft(), draft_id="draft-phrase"),
        CONTEXT,
    )

    with pytest.raises(ValueError, match="确认口令不匹配"):
        await ConfirmCharacterDraftAction(service).execute(
            ConfirmCharacterDraftRequest(
                "draft-phrase",
                "看起来没问题",
                character_id="must-not-exist",
            ),
            CONTEXT,
        )

    assert await repository.get_character("must-not-exist") is None
