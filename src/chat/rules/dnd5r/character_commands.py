"""Traditional QQ-ready commands for D&D 5r character import drafts."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re
from tempfile import TemporaryDirectory

from src.chat.actions import (
    ConfirmArchiveCharacterAction,
    ConfirmArchiveCharacterRequest,
    ConfirmCharacterDraftAction,
    ConfirmCharacterDraftRequest,
    ListOwnedCharactersAction,
    ListOwnedCharactersRequest,
    PrepareArchiveCharacterAction,
    PrepareArchiveCharacterRequest,
    PreviewCharacterDraftAction,
    PreviewCharacterDraftRequest,
    SaveCharacterDraftAction,
    SaveCharacterDraftRequest,
)
from src.chat.commands import CommandRegistry, CommandRequest, CommandResult
from src.trpg.characters import (
    CharacterArchivedError,
    CharacterManagementService,
    CharacterNotFoundError,
)
from src.trpg.importing.service import (
    CharacterDraftNotFoundError,
    CharacterDraftOwnershipError,
    CharacterDraftService,
    CharacterDraftValidationError,
)
from src.trpg.importing.xlsx import WorkbookInspectionError

from .xlsx_importer import Dnd5rXlsxDraftImporter


DEFAULT_MAX_XLSX_BYTES = 10 * 1024 * 1024
CONFIRMATION_PATTERN = re.compile(r"^确认\s+([A-Za-z0-9_-]{1,128})$")
DELETE_CONFIRMATION_PATTERN = re.compile(
    r"^确认删除\s+([A-Za-z0-9_-]{1,128})$"
)


@dataclass(slots=True)
class Dnd5rCharacterCommandHandler:
    draft_service: CharacterDraftService
    character_management_service: CharacterManagementService | None = None
    list_characters_action: ListOwnedCharactersAction | None = None
    max_xlsx_bytes: int = DEFAULT_MAX_XLSX_BYTES
    importer: Dnd5rXlsxDraftImporter = field(
        default_factory=Dnd5rXlsxDraftImporter
    )

    async def __call__(self, request: CommandRequest) -> CommandResult:
        parts = request.arguments.split(maxsplit=1)
        operation = parts[0].lower() if parts else "help"
        argument = parts[1].strip() if len(parts) > 1 else ""
        if operation == "import":
            return await self._import_xlsx(request)
        if operation in {"list", "ls"}:
            list_action = self.list_characters_action
            if list_action is None and self.character_management_service is not None:
                list_action = ListOwnedCharactersAction(
                    self.character_management_service
                )
            if list_action is None:
                return CommandResult("角色卡管理服务尚未启用。")
            result = await list_action.execute(
                ListOwnedCharactersRequest(), request.context
            )
            return CommandResult(
                result.authoritative_output or "没有可显示的角色卡"
            )
        if operation in {"delete", "remove"}:
            if not argument:
                return CommandResult("用法：.pc delete <角色ID>")
            if self.character_management_service is None:
                return CommandResult("角色卡管理服务尚未启用。")
            try:
                result = await PrepareArchiveCharacterAction(
                    self.character_management_service
                ).execute(
                    PrepareArchiveCharacterRequest(argument),
                    request.context,
                )
            except (CharacterNotFoundError, ValueError) as error:
                return CommandResult(str(error))
            return CommandResult(
                result.authoritative_output or "无法显示待删除角色卡"
            )
        if operation in {"preview", "draft"}:
            if not argument:
                return CommandResult("用法：.pc preview <草稿ID>")
            try:
                result = await PreviewCharacterDraftAction(
                    self.draft_service
                ).execute(
                    PreviewCharacterDraftRequest(argument),
                    request.context,
                )
            except (
                CharacterDraftNotFoundError,
                CharacterDraftOwnershipError,
                ValueError,
            ) as error:
                return CommandResult(str(error))
            return CommandResult(result.authoritative_output or "草稿没有可显示内容")
        return CommandResult(
            "角色卡命令：\n"
            "1. 先发送一个 .xlsx 文件\n"
            "2. 在 5 分钟内发送 .pc import\n"
            "3. 重新查看可用 .pc preview <草稿ID>\n"
            "4. 确认时发送 确认 <草稿ID>\n"
            "5. 查看正式角色卡：.pc list\n"
            "6. 删除角色卡：.pc delete <角色ID>"
        )

    async def _import_xlsx(self, request: CommandRequest) -> CommandResult:
        xlsx_files = tuple(
            file
            for file in request.context.files
            if file.name.lower().endswith(".xlsx")
        )
        if not xlsx_files:
            return CommandResult(
                "没有找到待导入的 XLSX。请先发送角色卡文件，"
                "再在 5 分钟内发送 .pc import。"
            )
        if len(xlsx_files) > 1:
            return CommandResult("一次只能导入一个 XLSX 文件，请分别发送。")
        file = xlsx_files[0]
        if file.size is not None and file.size > self.max_xlsx_bytes:
            return CommandResult(
                f"文件过大：当前限制为 {self.max_xlsx_bytes // (1024 * 1024)} MB。"
            )
        if request.context.file_provider is None:
            return CommandResult("当前 QQ 连接暂时无法读取上传文件，请稍后重试。")

        try:
            payload = await request.context.file_provider.read(
                file,
                max_bytes=self.max_xlsx_bytes,
            )
            with TemporaryDirectory(prefix="dice-bot-xlsx-") as temp_directory:
                path = Path(temp_directory) / "character.xlsx"
                path.write_bytes(payload)
                draft = self.importer.inspect_and_create_draft(path)
                draft.source = type(draft.source)(
                    source_type=draft.source.source_type,
                    original_filename=file.name,
                    sha256=draft.source.sha256,
                    byte_size=draft.source.byte_size,
                    local_path=None,
                )
                if draft.inspection is not None:
                    draft.inspection = type(draft.inspection)(
                        source=draft.source,
                        sheets=draft.inspection.sheets,
                        diagnostics=draft.inspection.diagnostics,
                    )
        except (ValueError, OSError, WorkbookInspectionError) as error:
            return CommandResult(f"XLSX 读取失败：{error}")

        result = await SaveCharacterDraftAction(self.draft_service).execute(
            SaveCharacterDraftRequest(draft),
            request.context,
        )
        return CommandResult(result.authoritative_output or "草稿已保存")


def register_dnd5r_character_commands(
    registry: CommandRegistry,
    draft_service: CharacterDraftService,
    *,
    character_management_service: CharacterManagementService | None = None,
    list_characters_action: ListOwnedCharactersAction | None = None,
    max_xlsx_bytes: int = DEFAULT_MAX_XLSX_BYTES,
) -> None:
    registry.register(
        "pc",
        Dnd5rCharacterCommandHandler(
            draft_service=draft_service,
            character_management_service=character_management_service,
            list_characters_action=list_characters_action,
            max_xlsx_bytes=max_xlsx_bytes,
        ),
    )


def create_dnd5r_confirmation_router(
    draft_service: CharacterDraftService,
    character_management_service: CharacterManagementService | None = None,
):
    async def route(text: str, context) -> CommandResult | None:
        stripped_text = text.strip()
        delete_match = DELETE_CONFIRMATION_PATTERN.fullmatch(stripped_text)
        if delete_match is not None and character_management_service is not None:
            character_id = delete_match.group(1)
            try:
                result = await ConfirmArchiveCharacterAction(
                    character_management_service
                ).execute(
                    ConfirmArchiveCharacterRequest(
                        character_id=character_id,
                        confirmation_text=stripped_text,
                    ),
                    context,
                )
            except (
                CharacterArchivedError,
                CharacterNotFoundError,
                ValueError,
            ) as error:
                return CommandResult(str(error))
            return CommandResult(
                result.authoritative_output or "角色卡已删除（可恢复）"
            )

        match = CONFIRMATION_PATTERN.fullmatch(stripped_text)
        if match is None:
            return None
        draft_id = match.group(1)
        try:
            result = await ConfirmCharacterDraftAction(draft_service).execute(
                ConfirmCharacterDraftRequest(
                    draft_id=draft_id,
                    confirmation_text=stripped_text,
                ),
                context,
            )
        except (
            CharacterDraftNotFoundError,
            CharacterDraftOwnershipError,
            CharacterDraftValidationError,
            ValueError,
        ) as error:
            return CommandResult(str(error))
        return CommandResult(result.authoritative_output or "角色卡已确认")

    return route


__all__ = [
    "DEFAULT_MAX_XLSX_BYTES",
    "Dnd5rCharacterCommandHandler",
    "create_dnd5r_confirmation_router",
    "register_dnd5r_character_commands",
]
