"""Platform- and ruleset-neutral models for external character imports."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class SourceSnapshot:
    """Identity of one immutable external source file."""

    source_type: str
    original_filename: str
    sha256: str
    byte_size: int
    local_path: Path | None = None


@dataclass(frozen=True, slots=True)
class InspectedCell:
    """One non-empty XLSX cell, including formula and cached result."""

    sheet: str
    coordinate: str
    value: Any
    raw_value: str | None = None
    formula: str | None = None
    cached_value: Any = None
    data_type: str | None = None
    style_id: int | None = None


@dataclass(frozen=True, slots=True)
class InspectedSheet:
    name: str
    state: str
    cells: tuple[InspectedCell, ...]
    merged_ranges: tuple[str, ...] = ()
    max_row: int = 0
    max_column: int = 0

    def cell(self, coordinate: str) -> InspectedCell | None:
        wanted = coordinate.strip().upper()
        return next(
            (cell for cell in self.cells if cell.coordinate.upper() == wanted),
            None,
        )


@dataclass(frozen=True, slots=True)
class WorkbookInspection:
    source: SourceSnapshot
    sheets: tuple[InspectedSheet, ...]
    diagnostics: tuple[str, ...] = ()

    def sheet(self, name: str) -> InspectedSheet | None:
        return next((sheet for sheet in self.sheets if sheet.name == name), None)

    def cell(self, sheet_name: str, coordinate: str) -> InspectedCell | None:
        sheet = self.sheet(sheet_name)
        return sheet.cell(coordinate) if sheet is not None else None


@dataclass(frozen=True, slots=True)
class SourceReference:
    """Auditable link from a draft field back to the source workbook."""

    source_sha256: str
    sheet: str
    coordinate: str
    original_value: Any
    formula: str | None = None
    cached_value: Any = None
    source_fragment: str | None = None


@dataclass(frozen=True, slots=True)
class DraftField:
    path: str
    value: Any
    sources: tuple[SourceReference, ...]
    confidence: float
    mapping_method: str
    manually_confirmed: bool = False


class ValidationSeverity(StrEnum):
    ERROR = "error"
    WARNING = "warning"


class CharacterDraftStatus(StrEnum):
    PENDING = "pending"
    CONFIRMED = "confirmed"


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    severity: ValidationSeverity
    code: str
    message: str
    field_path: str | None = None
    sources: tuple[SourceReference, ...] = ()


@dataclass(slots=True)
class CharacterDraft:
    """Unconfirmed import result. A draft is never a formal Character."""

    ruleset_key: str
    schema_version: int
    source: SourceSnapshot
    template_profile_id: str | None
    template_confidence: float
    inspection: WorkbookInspection | None = None
    fields: dict[str, DraftField] = field(default_factory=dict)
    extensions: dict[str, Any] = field(default_factory=dict)
    unmapped_regions: tuple[str, ...] = ()
    validation: tuple[ValidationIssue, ...] = ()

    @property
    def has_errors(self) -> bool:
        return any(
            issue.severity is ValidationSeverity.ERROR
            for issue in self.validation
        )


@dataclass(frozen=True, slots=True)
class StoredCharacterDraft:
    """One owner's durable draft and its confirmation state."""

    draft_id: str
    owner_platform: str
    owner_user_id: str
    owner_name: str
    draft: CharacterDraft
    status: CharacterDraftStatus
    confirmed_character_id: str | None
    created_at: str
    updated_at: str
    confirmed_at: str | None = None


__all__ = [
    "CharacterDraft",
    "CharacterDraftStatus",
    "DraftField",
    "InspectedCell",
    "InspectedSheet",
    "SourceReference",
    "SourceSnapshot",
    "StoredCharacterDraft",
    "ValidationIssue",
    "ValidationSeverity",
    "WorkbookInspection",
]
