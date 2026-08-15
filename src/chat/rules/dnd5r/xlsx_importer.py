"""D&D 5r XLSX -> CharacterDraft mapping with no database writes."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from src.trpg.importing import (
    CharacterDraft,
    DraftField,
    InspectedCell,
    SourceReference,
    ValidationIssue,
    ValidationSeverity,
    WorkbookInspection,
)
from src.trpg.importing.xlsx import (
    AnchorMatch,
    CellAnchor,
    TemplateMatch,
    TemplateProfile,
    WorkbookInspector,
    detect_template,
)

from .character_schema import DND5R_CHARACTER_SCHEMA


DND5R_XLSX_PROFILES = (
    TemplateProfile(
        profile_id="dnd5r.beiling-2024.v1",
        version=1,
        mapper_key="dice_command_sheet",
        anchors=(
            CellAnchor(
                "主要",
                "A1",
                "DND 5E2024",
                AnchorMatch.CONTAINS,
                weight=2,
            ),
            CellAnchor("主要", "B3", "角色名"),
            CellAnchor("主要", "B6", "主职业"),
            CellAnchor("骰娘导入", "B2", "人物卡导入", AnchorMatch.CONTAINS),
            CellAnchor("骰娘导入", "B8", ".st ", AnchorMatch.STARTS_WITH, weight=2),
            CellAnchor("骰娘导入", "N4", ".nn ", AnchorMatch.STARTS_WITH),
        ),
    ),
    TemplateProfile(
        profile_id="community.lightweight-cn.v1",
        version=1,
        mapper_key="label_adjacent",
        anchors=(
            CellAnchor("人物", "B4", "角色名", weight=2),
            CellAnchor("人物", "B8", "种族"),
            CellAnchor("属性", "C4", "职业", weight=2),
            CellAnchor("属性", "C6", "等级"),
            CellAnchor("属性", "H9", "力量"),
            CellAnchor("属性", "H14", "魅力"),
            CellAnchor("属性", "R4", "AC"),
        ),
    ),
)


ST_TOKEN_RE = re.compile(r"(?P<key>[^\s:]+):(?P<value>[^\s]+)")
ST_FIELD_PATHS = {
    "力量": "abilities.strength",
    "敏捷": "abilities.dexterity",
    "体质": "abilities.constitution",
    "智力": "abilities.intelligence",
    "感知": "abilities.wisdom",
    "魅力": "abilities.charisma",
    "hp": "combat.hit_points.current",
    "hpmax": "combat.hit_points.maximum",
    "ac": "combat.armor_class",
    "先攻": "combat.initiative",
    "dc": "combat.spell_save_dc",
    "pp": "senses.passive_perception",
    "熟练": "proficiency_bonus",
}


class Dnd5rXlsxDraftImporter:
    """Create a reviewable D&D 5r draft from an XLSX source."""

    ruleset_key = "dnd5r"

    def __init__(self, inspector: WorkbookInspector | None = None) -> None:
        self._inspector = inspector or WorkbookInspector()

    def inspect_and_create_draft(self, path: str | Path) -> CharacterDraft:
        return self.create_draft(self._inspector.inspect(path))

    def create_draft(self, inspection: WorkbookInspection) -> CharacterDraft:
        match = detect_template(inspection, DND5R_XLSX_PROFILES)
        draft = CharacterDraft(
            ruleset_key=self.ruleset_key,
            schema_version=DND5R_CHARACTER_SCHEMA.version,
            source=inspection.source,
            inspection=inspection,
            template_profile_id=match.profile.profile_id if match else None,
            template_confidence=match.confidence if match else 0.0,
            unmapped_regions=tuple(
                f"{sheet.name}!used-range({sheet.max_row}x{sheet.max_column})"
                for sheet in inspection.sheets
                if sheet.cells
            ),
        )
        issues: list[ValidationIssue] = []

        if match is None:
            issues.append(
                ValidationIssue(
                    severity=ValidationSeverity.WARNING,
                    code="UNKNOWN_TEMPLATE",
                    message="未识别出已支持模板；需要映射推断或人工确认。",
                )
            )
        elif match.profile.mapper_key == "dice_command_sheet":
            self._map_dice_command_sheet(inspection, draft, issues, match)
        elif match.profile.mapper_key == "label_adjacent":
            self._map_label_adjacent(inspection, draft, issues, match)

        draft.validation = tuple(self._validate(draft, issues))
        return draft

    def _map_dice_command_sheet(
        self,
        inspection: WorkbookInspection,
        draft: CharacterDraft,
        issues: list[ValidationIssue],
        match: TemplateMatch,
    ) -> None:
        method = f"template:{match.profile.profile_id}"
        self._add_text_cell(
            inspection, draft, "identity.name", "主要", "E3", method
        )
        self._add_text_cell(
            inspection,
            draft,
            "progression.primary_class",
            "主要",
            "E6",
            method,
        )
        self._add_integer_cell(
            inspection,
            draft,
            issues,
            "progression.total_level",
            "主要",
            "O6",
            method,
        )
        self._add_text_cell(
            inspection, draft, "identity.species", "主要", "T6", method
        )

        command_cell = inspection.cell("骰娘导入", "B8")
        if command_cell is None or not isinstance(command_cell.value, str):
            issues.append(
                ValidationIssue(
                    ValidationSeverity.ERROR,
                    "MISSING_ST_COMMAND",
                    "骰娘导入页缺少可读取的 .st 缓存结果。",
                )
            )
            return

        command = command_cell.value.strip()
        raw_tokens: dict[str, str] = {}
        unmapped_tokens: dict[str, str] = {}
        source_markers: dict[str, str] = {}
        for token_match in ST_TOKEN_RE.finditer(command):
            original_key = token_match.group("key")
            raw_value = token_match.group("value")
            raw_tokens[original_key] = raw_value
            base_key = original_key.rstrip("*")
            if base_key != original_key:
                source_markers[base_key] = original_key[len(base_key) :]
            field_path = ST_FIELD_PATHS.get(base_key)
            if field_path is None:
                unmapped_tokens[original_key] = raw_value
                continue
            self._add_integer_value(
                inspection,
                draft,
                issues,
                field_path,
                command_cell,
                raw_value,
                method,
                source_fragment=token_match.group(0),
            )

        draft.extensions["source_commands"] = {
            "st": command,
            "nn": self._cell_value(inspection, "骰娘导入", "N4"),
        }
        draft.extensions["raw_st_tokens"] = raw_tokens
        if unmapped_tokens:
            draft.extensions["unmapped_st_tokens"] = unmapped_tokens
        if source_markers:
            draft.extensions["uninterpreted_proficiency_markers"] = source_markers

    def _map_label_adjacent(
        self,
        inspection: WorkbookInspection,
        draft: CharacterDraft,
        issues: list[ValidationIssue],
        match: TemplateMatch,
    ) -> None:
        method = f"template:{match.profile.profile_id}"
        text_mappings = (
            ("identity.name", "人物", "B4", "角色名", "C4"),
            ("identity.species", "人物", "B8", "种族", "C8"),
            ("identity.background", "人物", "B19", "背景", "C19"),
            ("progression.primary_class", "属性", "C4", "职业", "E4"),
        )
        for field_path, sheet, label_cell, label, value_cell in text_mappings:
            if self._label_matches(inspection, sheet, label_cell, label):
                self._add_text_cell(
                    inspection, draft, field_path, sheet, value_cell, method
                )

        integer_mappings = (
            ("progression.total_level", "属性", "C6", "等级", "E6"),
            ("proficiency_bonus", "属性", "G6", "熟练加值", "I6"),
            ("combat.hit_points.current", "属性", "L4", "生命值", "L5"),
            ("combat.hit_points.maximum", "属性", "N4", "最大值", "N5"),
            ("combat.armor_class", "属性", "R4", "AC", "R5"),
            ("combat.initiative", "属性", "T4", "先攻", "T5"),
            ("combat.speed", "属性", "V4", "速度", "V5"),
        )
        for field_path, sheet, label_cell, label, value_cell in integer_mappings:
            if self._label_matches(inspection, sheet, label_cell, label):
                self._add_integer_cell(
                    inspection,
                    draft,
                    issues,
                    field_path,
                    sheet,
                    value_cell,
                    method,
                )

        for row, (ability, label) in enumerate(
            (
                ("strength", "力量"),
                ("dexterity", "敏捷"),
                ("constitution", "体质"),
                ("intelligence", "智力"),
                ("wisdom", "感知"),
                ("charisma", "魅力"),
            ),
            start=9,
        ):
            if self._label_matches(inspection, "属性", f"H{row}", label):
                self._add_integer_cell(
                    inspection,
                    draft,
                    issues,
                    f"abilities.{ability}",
                    "属性",
                    f"J{row}",
                    method,
                )

    def _add_text_cell(
        self,
        inspection: WorkbookInspection,
        draft: CharacterDraft,
        field_path: str,
        sheet: str,
        coordinate: str,
        method: str,
    ) -> None:
        cell = inspection.cell(sheet, coordinate)
        if cell is None or cell.value is None:
            return
        value = str(cell.value).strip()
        if not value:
            return
        draft.fields[field_path] = DraftField(
            path=field_path,
            value=value,
            sources=(self._source_reference(inspection, cell),),
            confidence=1.0,
            mapping_method=method,
        )

    def _add_integer_cell(
        self,
        inspection: WorkbookInspection,
        draft: CharacterDraft,
        issues: list[ValidationIssue],
        field_path: str,
        sheet: str,
        coordinate: str,
        method: str,
    ) -> None:
        cell = inspection.cell(sheet, coordinate)
        if cell is None:
            return
        if cell.value is None and cell.formula is not None:
            source = self._source_reference(inspection, cell)
            issues.append(
                ValidationIssue(
                    ValidationSeverity.ERROR,
                    "FORMULA_CACHE_MISSING",
                    "公式没有缓存结果；请用 Excel/WPS 打开并保存后重新上传。",
                    field_path,
                    (source,),
                )
            )
            return
        self._add_integer_value(
            inspection,
            draft,
            issues,
            field_path,
            cell,
            cell.value,
            method,
        )

    def _add_integer_value(
        self,
        inspection: WorkbookInspection,
        draft: CharacterDraft,
        issues: list[ValidationIssue],
        field_path: str,
        cell: InspectedCell,
        raw_value: Any,
        method: str,
        *,
        source_fragment: str | None = None,
    ) -> None:
        source = self._source_reference(
            inspection, cell, source_fragment=source_fragment
        )
        try:
            value = self._coerce_integer(raw_value)
        except ValueError:
            value = raw_value
            issues.append(
                ValidationIssue(
                    ValidationSeverity.ERROR,
                    "INVALID_INTEGER",
                    f"{field_path} 无法转换为整数，需要人工确认。",
                    field_path,
                    (source,),
                )
            )
        draft.fields[field_path] = DraftField(
            path=field_path,
            value=value,
            sources=(source,),
            confidence=1.0,
            mapping_method=method,
        )

    def _validate(
        self,
        draft: CharacterDraft,
        existing: list[ValidationIssue],
    ) -> list[ValidationIssue]:
        issues = list(existing)
        invalid_integer_paths = {
            issue.field_path
            for issue in issues
            if issue.code == "INVALID_INTEGER"
        }
        for definition in DND5R_CHARACTER_SCHEMA.fields:
            draft_field = draft.fields.get(definition.path)
            if draft_field is None:
                if definition.required:
                    issues.append(
                        ValidationIssue(
                            ValidationSeverity.ERROR,
                            "REQUIRED_FIELD_MISSING",
                            f"缺少必填字段：{definition.path}",
                            definition.path,
                        )
                    )
                continue
            value = draft_field.value
            if definition.value_type == "integer":
                if definition.path in invalid_integer_paths:
                    continue
                if isinstance(value, bool) or not isinstance(value, int):
                    issues.append(
                        ValidationIssue(
                            ValidationSeverity.ERROR,
                            "INVALID_INTEGER",
                            f"{definition.path} 必须是整数。",
                            definition.path,
                            draft_field.sources,
                        )
                    )
                    continue
                if (
                    definition.recommended_minimum is not None
                    and value < definition.recommended_minimum
                ) or (
                    definition.recommended_maximum is not None
                    and value > definition.recommended_maximum
                ):
                    issues.append(
                        ValidationIssue(
                            ValidationSeverity.WARNING,
                            "OUTSIDE_RECOMMENDED_RANGE",
                            f"{definition.path}={value} 超出当前规则建议范围；不会自动修改。",
                            definition.path,
                            draft_field.sources,
                        )
                    )
            elif definition.value_type == "string" and (
                not isinstance(value, str) or not value.strip()
            ):
                issues.append(
                    ValidationIssue(
                        ValidationSeverity.ERROR,
                        "INVALID_STRING",
                        f"{definition.path} 必须是非空文字。",
                        definition.path,
                        draft_field.sources,
                    )
                )
        return issues

    @staticmethod
    def _coerce_integer(value: Any) -> int:
        if isinstance(value, bool) or value is None:
            raise ValueError
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            if value.is_integer():
                return int(value)
            raise ValueError
        try:
            number = Decimal(str(value).strip())
        except (InvalidOperation, ValueError):
            raise ValueError from None
        if number != number.to_integral_value():
            raise ValueError
        return int(number)

    @staticmethod
    def _source_reference(
        inspection: WorkbookInspection,
        cell: InspectedCell,
        *,
        source_fragment: str | None = None,
    ) -> SourceReference:
        return SourceReference(
            source_sha256=inspection.source.sha256,
            sheet=cell.sheet,
            coordinate=cell.coordinate,
            original_value=cell.value,
            formula=cell.formula,
            cached_value=cell.cached_value,
            source_fragment=source_fragment,
        )

    @staticmethod
    def _label_matches(
        inspection: WorkbookInspection,
        sheet: str,
        coordinate: str,
        expected: str,
    ) -> bool:
        value = Dnd5rXlsxDraftImporter._cell_value(
            inspection, sheet, coordinate
        )
        return str(value).strip().casefold() == expected.strip().casefold()

    @staticmethod
    def _cell_value(
        inspection: WorkbookInspection,
        sheet: str,
        coordinate: str,
    ) -> Any:
        cell = inspection.cell(sheet, coordinate)
        return cell.value if cell is not None else None


__all__ = ["DND5R_XLSX_PROFILES", "Dnd5rXlsxDraftImporter"]
