"""JSON serialization for durable, auditable character import drafts."""

from __future__ import annotations

import json
from typing import Any

from .models import (
    CharacterDraft,
    DraftField,
    InspectedCell,
    InspectedSheet,
    SourceReference,
    SourceSnapshot,
    ValidationIssue,
    ValidationSeverity,
    WorkbookInspection,
)


def serialize_character_draft(draft: CharacterDraft) -> str:
    return json.dumps(
        character_draft_to_dict(draft),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def deserialize_character_draft(payload: str) -> CharacterDraft:
    try:
        data = json.loads(payload)
    except (TypeError, json.JSONDecodeError) as error:
        raise ValueError("角色导入草稿不是有效 JSON") from error
    if not isinstance(data, dict):
        raise ValueError("角色导入草稿必须是 JSON 对象")
    return character_draft_from_dict(data)


def character_draft_to_dict(draft: CharacterDraft) -> dict[str, Any]:
    return {
        "ruleset_key": draft.ruleset_key,
        "schema_version": draft.schema_version,
        "source": _source_to_dict(draft.source),
        "template_profile_id": draft.template_profile_id,
        "template_confidence": draft.template_confidence,
        "inspection": (
            _inspection_to_dict(draft.inspection)
            if draft.inspection is not None
            else None
        ),
        "fields": {
            path: _draft_field_to_dict(field)
            for path, field in draft.fields.items()
        },
        "extensions": draft.extensions,
        "unmapped_regions": list(draft.unmapped_regions),
        "validation": [_issue_to_dict(issue) for issue in draft.validation],
    }


def character_draft_from_dict(data: dict[str, Any]) -> CharacterDraft:
    source = _source_from_dict(_require_dict(data, "source"))
    inspection_data = data.get("inspection")
    inspection = (
        _inspection_from_dict(inspection_data, source)
        if isinstance(inspection_data, dict)
        else None
    )
    fields_data = _require_dict(data, "fields")
    validation_data = data.get("validation", [])
    if not isinstance(validation_data, list):
        raise ValueError("草稿 validation 必须是列表")
    extensions = data.get("extensions", {})
    if not isinstance(extensions, dict):
        raise ValueError("草稿 extensions 必须是对象")
    unmapped_regions = data.get("unmapped_regions", [])
    if not isinstance(unmapped_regions, list):
        raise ValueError("草稿 unmapped_regions 必须是列表")
    return CharacterDraft(
        ruleset_key=str(data["ruleset_key"]),
        schema_version=int(data["schema_version"]),
        source=source,
        template_profile_id=(
            str(data["template_profile_id"])
            if data.get("template_profile_id") is not None
            else None
        ),
        template_confidence=float(data.get("template_confidence", 0.0)),
        inspection=inspection,
        fields={
            str(path): _draft_field_from_dict(_ensure_dict(field))
            for path, field in fields_data.items()
        },
        extensions=dict(extensions),
        unmapped_regions=tuple(str(item) for item in unmapped_regions),
        validation=tuple(
            _issue_from_dict(_ensure_dict(issue)) for issue in validation_data
        ),
    )


def draft_confirmation_payload(draft: CharacterDraft) -> dict[str, Any]:
    """Compact ruleset input; the full inspection remains in the draft table."""

    return {
        "ruleset_key": draft.ruleset_key,
        "schema_version": draft.schema_version,
        "fields": {path: field.value for path, field in draft.fields.items()},
        "field_provenance": {
            path: [_source_reference_to_dict(source) for source in field.sources]
            for path, field in draft.fields.items()
        },
        "extensions": draft.extensions,
        "source": _source_to_dict(draft.source),
        "template_profile_id": draft.template_profile_id,
    }


def _source_to_dict(source: SourceSnapshot) -> dict[str, Any]:
    return {
        "source_type": source.source_type,
        "original_filename": source.original_filename,
        "sha256": source.sha256,
        "byte_size": source.byte_size,
    }


def _source_from_dict(data: dict[str, Any]) -> SourceSnapshot:
    return SourceSnapshot(
        source_type=str(data["source_type"]),
        original_filename=str(data["original_filename"]),
        sha256=str(data["sha256"]),
        byte_size=int(data["byte_size"]),
        local_path=None,
    )


def _source_reference_to_dict(source: SourceReference) -> dict[str, Any]:
    return {
        "source_sha256": source.source_sha256,
        "sheet": source.sheet,
        "coordinate": source.coordinate,
        "original_value": source.original_value,
        "formula": source.formula,
        "cached_value": source.cached_value,
        "source_fragment": source.source_fragment,
    }


def _source_reference_from_dict(data: dict[str, Any]) -> SourceReference:
    return SourceReference(
        source_sha256=str(data["source_sha256"]),
        sheet=str(data["sheet"]),
        coordinate=str(data["coordinate"]),
        original_value=data.get("original_value"),
        formula=data.get("formula"),
        cached_value=data.get("cached_value"),
        source_fragment=data.get("source_fragment"),
    )


def _draft_field_to_dict(field: DraftField) -> dict[str, Any]:
    return {
        "path": field.path,
        "value": field.value,
        "sources": [_source_reference_to_dict(source) for source in field.sources],
        "confidence": field.confidence,
        "mapping_method": field.mapping_method,
        "manually_confirmed": field.manually_confirmed,
    }


def _draft_field_from_dict(data: dict[str, Any]) -> DraftField:
    sources = data.get("sources", [])
    if not isinstance(sources, list):
        raise ValueError("草稿字段 sources 必须是列表")
    return DraftField(
        path=str(data["path"]),
        value=data.get("value"),
        sources=tuple(
            _source_reference_from_dict(_ensure_dict(source))
            for source in sources
        ),
        confidence=float(data["confidence"]),
        mapping_method=str(data["mapping_method"]),
        manually_confirmed=bool(data.get("manually_confirmed", False)),
    )


def _issue_to_dict(issue: ValidationIssue) -> dict[str, Any]:
    return {
        "severity": issue.severity.value,
        "code": issue.code,
        "message": issue.message,
        "field_path": issue.field_path,
        "sources": [_source_reference_to_dict(source) for source in issue.sources],
    }


def _issue_from_dict(data: dict[str, Any]) -> ValidationIssue:
    sources = data.get("sources", [])
    if not isinstance(sources, list):
        raise ValueError("校验问题 sources 必须是列表")
    return ValidationIssue(
        severity=ValidationSeverity(str(data["severity"])),
        code=str(data["code"]),
        message=str(data["message"]),
        field_path=(
            str(data["field_path"])
            if data.get("field_path") is not None
            else None
        ),
        sources=tuple(
            _source_reference_from_dict(_ensure_dict(source))
            for source in sources
        ),
    )


def _inspection_to_dict(inspection: WorkbookInspection) -> dict[str, Any]:
    return {
        "sheets": [
            {
                "name": sheet.name,
                "state": sheet.state,
                "cells": [
                    {
                        "sheet": cell.sheet,
                        "coordinate": cell.coordinate,
                        "value": cell.value,
                        "raw_value": cell.raw_value,
                        "formula": cell.formula,
                        "cached_value": cell.cached_value,
                        "data_type": cell.data_type,
                        "style_id": cell.style_id,
                    }
                    for cell in sheet.cells
                ],
                "merged_ranges": list(sheet.merged_ranges),
                "max_row": sheet.max_row,
                "max_column": sheet.max_column,
            }
            for sheet in inspection.sheets
        ],
        "diagnostics": list(inspection.diagnostics),
    }


def _inspection_from_dict(
    data: dict[str, Any],
    source: SourceSnapshot,
) -> WorkbookInspection:
    sheets_data = data.get("sheets", [])
    if not isinstance(sheets_data, list):
        raise ValueError("工作簿检查 sheets 必须是列表")
    sheets: list[InspectedSheet] = []
    for sheet_data_raw in sheets_data:
        sheet_data = _ensure_dict(sheet_data_raw)
        cells_data = sheet_data.get("cells", [])
        if not isinstance(cells_data, list):
            raise ValueError("工作表 cells 必须是列表")
        sheets.append(
            InspectedSheet(
                name=str(sheet_data["name"]),
                state=str(sheet_data["state"]),
                cells=tuple(
                    _cell_from_dict(_ensure_dict(cell)) for cell in cells_data
                ),
                merged_ranges=tuple(
                    str(item) for item in sheet_data.get("merged_ranges", [])
                ),
                max_row=int(sheet_data.get("max_row", 0)),
                max_column=int(sheet_data.get("max_column", 0)),
            )
        )
    return WorkbookInspection(
        source=source,
        sheets=tuple(sheets),
        diagnostics=tuple(str(item) for item in data.get("diagnostics", [])),
    )


def _cell_from_dict(data: dict[str, Any]) -> InspectedCell:
    style_id = data.get("style_id")
    return InspectedCell(
        sheet=str(data["sheet"]),
        coordinate=str(data["coordinate"]),
        value=data.get("value"),
        raw_value=data.get("raw_value"),
        formula=data.get("formula"),
        cached_value=data.get("cached_value"),
        data_type=data.get("data_type"),
        style_id=int(style_id) if style_id is not None else None,
    )


def _require_dict(data: dict[str, Any], key: str) -> dict[str, Any]:
    return _ensure_dict(data.get(key), field_name=key)


def _ensure_dict(
    value: Any,
    *,
    field_name: str = "value",
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{field_name} 必须是对象")
    return value


__all__ = [
    "character_draft_from_dict",
    "character_draft_to_dict",
    "deserialize_character_draft",
    "draft_confirmation_payload",
    "serialize_character_draft",
]
