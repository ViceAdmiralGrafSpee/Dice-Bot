"""Robust, read-only XLSX structure inspection based on OOXML."""

from __future__ import annotations

import hashlib
import posixpath
import re
from pathlib import Path
from typing import Any
from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile

from ..models import (
    InspectedCell,
    InspectedSheet,
    SourceSnapshot,
    WorkbookInspection,
)


MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
OFFICE_REL_NS = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
)
PACKAGE_REL_NS = (
    "http://schemas.openxmlformats.org/package/2006/relationships"
)
CELL_COORDINATE_RE = re.compile(r"^([A-Z]+)([1-9][0-9]*)$")


class WorkbookInspectionError(ValueError):
    """Raised when an input is not a readable XLSX package."""


class WorkbookInspector:
    """Extract workbook facts without trusting a fixed two-dimensional table."""

    def inspect(self, path: str | Path) -> WorkbookInspection:
        source_path = Path(path)
        payload = source_path.read_bytes()
        source = SourceSnapshot(
            source_type="xlsx",
            original_filename=source_path.name,
            sha256=hashlib.sha256(payload).hexdigest(),
            byte_size=len(payload),
            local_path=source_path,
        )

        try:
            with ZipFile(source_path) as archive:
                shared_strings = self._read_shared_strings(archive)
                workbook_root = self._read_xml(archive, "xl/workbook.xml")
                relationships = self._read_relationships(archive)
                sheets: list[InspectedSheet] = []
                diagnostics: list[str] = []

                sheets_node = workbook_root.find(f"{{{MAIN_NS}}}sheets")
                if sheets_node is None:
                    raise WorkbookInspectionError("XLSX 缺少工作表列表")

                for sheet_node in sheets_node:
                    name = sheet_node.attrib.get("name", "")
                    state = sheet_node.attrib.get("state", "visible")
                    relationship_id = sheet_node.attrib.get(
                        f"{{{OFFICE_REL_NS}}}id"
                    )
                    target = relationships.get(relationship_id or "")
                    if not name or target is None:
                        diagnostics.append(f"跳过无法定位的工作表：{name or '<unnamed>'}")
                        continue
                    sheets.append(
                        self._inspect_sheet(
                            archive,
                            target,
                            name,
                            state,
                            shared_strings,
                            diagnostics,
                        )
                    )
        except (BadZipFile, KeyError, ElementTree.ParseError) as error:
            raise WorkbookInspectionError("文件不是可读取的 XLSX 工作簿") from error

        return WorkbookInspection(
            source=source,
            sheets=tuple(sheets),
            diagnostics=tuple(diagnostics),
        )

    @staticmethod
    def _read_xml(archive: ZipFile, member: str) -> ElementTree.Element:
        return ElementTree.fromstring(archive.read(member))

    def _read_relationships(self, archive: ZipFile) -> dict[str, str]:
        root = self._read_xml(archive, "xl/_rels/workbook.xml.rels")
        relationships: dict[str, str] = {}
        for node in root.findall(f"{{{PACKAGE_REL_NS}}}Relationship"):
            relationship_id = node.attrib.get("Id")
            target = node.attrib.get("Target")
            if not relationship_id or not target:
                continue
            if target.startswith("/"):
                normalized = posixpath.normpath(target.lstrip("/"))
            else:
                normalized = posixpath.normpath(posixpath.join("xl", target))
            relationships[relationship_id] = normalized
        return relationships

    def _read_shared_strings(self, archive: ZipFile) -> tuple[str, ...]:
        if "xl/sharedStrings.xml" not in archive.namelist():
            return ()
        root = self._read_xml(archive, "xl/sharedStrings.xml")
        return tuple(
            "".join(text.text or "" for text in item.iter(f"{{{MAIN_NS}}}t"))
            for item in root.findall(f"{{{MAIN_NS}}}si")
        )

    def _inspect_sheet(
        self,
        archive: ZipFile,
        target: str,
        name: str,
        state: str,
        shared_strings: tuple[str, ...],
        diagnostics: list[str],
    ) -> InspectedSheet:
        root = self._read_xml(archive, target)
        cells: list[InspectedCell] = []
        max_row = 0
        max_column = 0

        for cell_node in root.findall(f".//{{{MAIN_NS}}}c"):
            coordinate = cell_node.attrib.get("r", "")
            match = CELL_COORDINATE_RE.match(coordinate.upper())
            if match is None:
                diagnostics.append(f"{name} 含无效单元格坐标：{coordinate}")
                continue

            row = int(match.group(2))
            column = self._column_number(match.group(1))
            max_row = max(max_row, row)
            max_column = max(max_column, column)

            data_type = cell_node.attrib.get("t")
            style_text = cell_node.attrib.get("s")
            style_id = int(style_text) if style_text is not None else None
            formula_node = cell_node.find(f"{{{MAIN_NS}}}f")
            formula = formula_node.text if formula_node is not None else None
            value_node = cell_node.find(f"{{{MAIN_NS}}}v")
            raw_value = value_node.text if value_node is not None else None
            inline_value = self._inline_string(cell_node)
            parsed_value = self._parse_value(
                data_type,
                raw_value,
                inline_value,
                shared_strings,
            )
            cached_value = parsed_value if formula is not None else None

            if formula is not None and raw_value is None and inline_value is None:
                diagnostics.append(
                    f"{name}!{coordinate} 的公式没有缓存结果；请用 Excel/WPS 打开保存后重试"
                )

            if (
                parsed_value is not None
                or formula is not None
                or raw_value is not None
                or inline_value is not None
            ):
                cells.append(
                    InspectedCell(
                        sheet=name,
                        coordinate=coordinate,
                        value=parsed_value,
                        raw_value=inline_value if inline_value is not None else raw_value,
                        formula=formula,
                        cached_value=cached_value,
                        data_type=data_type,
                        style_id=style_id,
                    )
                )

        merged_ranges = tuple(
            node.attrib["ref"]
            for node in root.findall(f".//{{{MAIN_NS}}}mergeCell")
            if "ref" in node.attrib
        )
        for validation in root.findall(f".//{{{MAIN_NS}}}dataValidation"):
            if validation.attrib.get("type") == "any":
                diagnostics.append(
                    f"{name} 含非标准 dataValidation type=any；已忽略该验证定义"
                )

        return InspectedSheet(
            name=name,
            state=state,
            cells=tuple(cells),
            merged_ranges=merged_ranges,
            max_row=max_row,
            max_column=max_column,
        )

    @staticmethod
    def _inline_string(cell_node: ElementTree.Element) -> str | None:
        inline = cell_node.find(f"{{{MAIN_NS}}}is")
        if inline is None:
            return None
        return "".join(
            text.text or "" for text in inline.iter(f"{{{MAIN_NS}}}t")
        )

    @staticmethod
    def _parse_value(
        data_type: str | None,
        raw_value: str | None,
        inline_value: str | None,
        shared_strings: tuple[str, ...],
    ) -> Any:
        if inline_value is not None:
            return inline_value
        if raw_value is None:
            return None
        if data_type == "s":
            try:
                return shared_strings[int(raw_value)]
            except (IndexError, ValueError):
                return raw_value
        if data_type in {"str", "e"}:
            return raw_value
        if data_type == "b":
            return raw_value == "1"
        try:
            number = float(raw_value)
        except ValueError:
            return raw_value
        return int(number) if number.is_integer() else number

    @staticmethod
    def _column_number(letters: str) -> int:
        number = 0
        for letter in letters:
            number = number * 26 + ord(letter) - ord("A") + 1
        return number


__all__ = ["WorkbookInspectionError", "WorkbookInspector"]
