from __future__ import annotations

from dataclasses import dataclass
from html import escape
from pathlib import Path
import re
from zipfile import ZIP_DEFLATED, ZipFile

from src.chat.rules.dnd5r import Dnd5rXlsxDraftImporter
from src.trpg.importing import ValidationSeverity
from src.trpg.importing.xlsx import WorkbookInspector


@dataclass(frozen=True)
class FormulaCell:
    formula: str
    cached: str | int | float | None


def _write_xlsx(
    path: Path,
    sheets: list[
        tuple[
            str,
            str,
            dict[str, str | int | float | FormulaCell],
            tuple[str, ...],
            bool,
        ]
    ],
) -> None:
    workbook_sheets = []
    workbook_relationships = []
    overrides = []
    with ZipFile(path, "w", ZIP_DEFLATED) as archive:
        for index, (name, state, cells, merges, invalid_validation) in enumerate(
            sheets,
            start=1,
        ):
            workbook_sheets.append(
                f'<sheet name="{escape(name)}" sheetId="{index}" '
                f'state="{state}" r:id="rId{index}"/>'
            )
            workbook_relationships.append(
                f'<Relationship Id="rId{index}" '
                'Type="http://schemas.openxmlformats.org/officeDocument/'
                f'2006/relationships/worksheet" Target="worksheets/sheet{index}.xml"/>'
            )
            overrides.append(
                f'<Override PartName="/xl/worksheets/sheet{index}.xml" '
                'ContentType="application/vnd.openxmlformats-officedocument.'
                'spreadsheetml.worksheet+xml"/>'
            )
            rows: dict[int, list[str]] = {}
            for coordinate, value in cells.items():
                row = int(re.search(r"[0-9]+$", coordinate).group())
                if isinstance(value, FormulaCell):
                    cell_type = ' t="str"' if isinstance(value.cached, str) else ""
                    cached = (
                        ""
                        if value.cached is None
                        else f"<v>{escape(str(value.cached))}</v>"
                    )
                    cell_xml = (
                        f'<c r="{coordinate}"{cell_type}>'
                        f"<f>{escape(value.formula)}</f>{cached}</c>"
                    )
                elif isinstance(value, str):
                    cell_xml = (
                        f'<c r="{coordinate}" t="inlineStr"><is><t>'
                        f"{escape(value)}</t></is></c>"
                    )
                else:
                    cell_xml = f'<c r="{coordinate}"><v>{value}</v></c>'
                rows.setdefault(row, []).append(cell_xml)
            sheet_data = "".join(
                f'<row r="{row}">{"".join(row_cells)}</row>'
                for row, row_cells in sorted(rows.items())
            )
            merge_xml = (
                ""
                if not merges
                else f'<mergeCells count="{len(merges)}">'
                + "".join(f'<mergeCell ref="{item}"/>' for item in merges)
                + "</mergeCells>"
            )
            validation_xml = (
                '<dataValidations count="1"><dataValidation type="any" '
                'sqref="A1"/></dataValidations>'
                if invalid_validation
                else ""
            )
            archive.writestr(
                f"xl/worksheets/sheet{index}.xml",
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<worksheet xmlns="http://schemas.openxmlformats.org/'
                'spreadsheetml/2006/main">'
                f"<sheetData>{sheet_data}</sheetData>{merge_xml}"
                f"{validation_xml}</worksheet>",
            )

        archive.writestr(
            "xl/workbook.xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/'
            'spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.'
            'org/officeDocument/2006/relationships">'
            f'<sheets>{"".join(workbook_sheets)}</sheets></workbook>',
        )
        archive.writestr(
            "xl/_rels/workbook.xml.rels",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/'
            f'2006/relationships">{"".join(workbook_relationships)}</Relationships>',
        )
        archive.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/'
            'content-types"><Default Extension="xml" ContentType="application/'
            'xml"/><Override PartName="/xl/workbook.xml" ContentType="application/'
            'vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            f'{"".join(overrides)}</Types>',
        )


def _modern_sheets(
    *,
    strength: str = "16",
) -> list[tuple[str, str, dict, tuple[str, ...], bool]]:
    return [
        (
            "主要",
            "visible",
            {
                "A1": "DND 5E2024 人物卡<模板>",
                "B3": "角色名",
                "E3": "阿莉娅",
                "B6": "主职业",
                "E6": "战士",
                "O6": 3,
                "R6": "种族",
                "T6": "人类",
            },
            ("A1:Z1",),
            True,
        ),
        (
            "骰娘导入",
            "visible",
            {
                "B2": "人物卡导入，基本适合全部骰娘",
                "B8": FormulaCell(
                    "主要!$AV$1",
                    ".st 力量:"
                    f"{strength} 敏捷*:14 体质:15 智力:10 感知:12 魅力:8 "
                    "hp:24 hpmax:24 先攻:2 ac:17 dc:12 pp:13 熟练:2 运动*:0",
                ),
                "N4": FormulaCell('".nn "&主要!$E$3', ".nn 阿莉娅"),
            },
            (),
            False,
        ),
        (
            "规则数据库",
            "hidden",
            {"A1": "此页也应被识别但不能误当角色字段"},
            (),
            False,
        ),
    ]


def test_workbook_inspector_keeps_structure_formula_cache_and_diagnostics(
    tmp_path,
) -> None:
    path = tmp_path / "任意文件名.xlsx"
    sheets = _modern_sheets()
    sheets[2][2]["B2"] = FormulaCell("1+1", None)
    _write_xlsx(path, sheets)

    inspection = WorkbookInspector().inspect(path)

    assert [sheet.name for sheet in inspection.sheets] == [
        "主要",
        "骰娘导入",
        "规则数据库",
    ]
    assert inspection.sheet("规则数据库").state == "hidden"
    assert inspection.sheet("主要").merged_ranges == ("A1:Z1",)
    command = inspection.cell("骰娘导入", "B8")
    assert command.formula == "主要!$AV$1"
    assert command.cached_value.startswith(".st 力量:16")
    assert any("type=any" in diagnostic for diagnostic in inspection.diagnostics)
    assert any("公式没有缓存结果" in diagnostic for diagnostic in inspection.diagnostics)


def test_modern_2024_template_creates_reviewable_dnd5r_draft_only(
    tmp_path,
) -> None:
    path = tmp_path / "文件名不参与识别.xlsx"
    _write_xlsx(path, _modern_sheets())

    draft = Dnd5rXlsxDraftImporter().inspect_and_create_draft(path)

    assert draft.ruleset_key == "dnd5r"
    assert draft.template_profile_id == "dnd5r.beiling-2024.v1"
    assert draft.fields["identity.name"].value == "阿莉娅"
    assert draft.fields["progression.primary_class"].value == "战士"
    assert draft.fields["progression.total_level"].value == 3
    assert draft.fields["abilities.strength"].value == 16
    assert draft.fields["combat.hit_points.maximum"].value == 24
    assert draft.fields["combat.armor_class"].value == 17
    assert draft.fields["abilities.strength"].sources[0].coordinate == "B8"
    assert draft.fields["abilities.strength"].sources[0].source_fragment == "力量:16"
    assert draft.extensions["unmapped_st_tokens"] == {"运动*": "0"}
    assert draft.extensions["uninterpreted_proficiency_markers"] == {
        "敏捷": "*",
        "运动": "*",
    }
    assert draft.inspection is not None
    assert draft.has_errors is False
    assert list(tmp_path.glob("*.sqlite3")) == []


def test_invalid_mechanical_value_is_error_and_is_not_corrected(tmp_path) -> None:
    path = tmp_path / "invalid-value.xlsx"
    _write_xlsx(path, _modern_sheets(strength="大概18"))

    draft = Dnd5rXlsxDraftImporter().inspect_and_create_draft(path)

    assert draft.fields["abilities.strength"].value == "大概18"
    assert any(
        issue.severity is ValidationSeverity.ERROR
        and issue.code == "INVALID_INTEGER"
        and issue.field_path == "abilities.strength"
        for issue in draft.validation
    )


def test_lightweight_template_uses_label_guarded_mapping(tmp_path) -> None:
    path = tmp_path / "another-name.xlsx"
    ability_cells = {}
    for row, (label, value) in enumerate(
        (("力量", 9), ("敏捷", 19), ("体质", 14), ("智力", 12), ("感知", 16), ("魅力", 10)),
        start=9,
    ):
        ability_cells[f"H{row}"] = label
        ability_cells[f"J{row}"] = value
    _write_xlsx(
        path,
        [
            (
                "人物",
                "visible",
                {
                    "B4": "角色名",
                    "C4": "莉薇尔",
                    "B8": "种族",
                    "C8": "精灵",
                    "B19": "背景",
                    "C19": "竖琴手特工",
                },
                (),
                False,
            ),
            (
                "属性",
                "visible",
                {
                    "C4": "职业",
                    "E4": "游侠",
                    "C6": "等级",
                    "E6": 1,
                    "G6": "熟练加值",
                    "I6": FormulaCell("INT((E6+7)/4)", 2),
                    "L4": "生命值",
                    "L5": 13,
                    "N4": "最大值",
                    "N5": 13,
                    "R4": "AC",
                    "R5": 16,
                    "T4": "先攻",
                    "T5": 4,
                    "V4": "速度",
                    "V5": 35,
                    **ability_cells,
                },
                (),
                False,
            ),
        ],
    )

    draft = Dnd5rXlsxDraftImporter().inspect_and_create_draft(path)

    assert draft.template_profile_id == "community.lightweight-cn.v1"
    assert draft.fields["identity.name"].value == "莉薇尔"
    assert draft.fields["identity.background"].value == "竖琴手特工"
    assert draft.fields["progression.total_level"].value == 1
    assert draft.fields["proficiency_bonus"].value == 2
    assert draft.fields["abilities.dexterity"].value == 19
    assert draft.fields["combat.speed"].value == 35
    assert draft.has_errors is False
