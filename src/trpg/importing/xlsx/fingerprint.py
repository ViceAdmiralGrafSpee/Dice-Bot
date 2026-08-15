"""Declarative XLSX template fingerprints; filenames are never fingerprints."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from ..models import WorkbookInspection


class AnchorMatch(StrEnum):
    EQUALS = "equals"
    CONTAINS = "contains"
    STARTS_WITH = "starts_with"


@dataclass(frozen=True, slots=True)
class CellAnchor:
    sheet: str
    coordinate: str | None = None
    expected: str | None = None
    match: AnchorMatch = AnchorMatch.EQUALS
    weight: float = 1.0
    required: bool = True


@dataclass(frozen=True, slots=True)
class TemplateProfile:
    profile_id: str
    version: int
    mapper_key: str
    anchors: tuple[CellAnchor, ...]
    minimum_confidence: float = 0.8


@dataclass(frozen=True, slots=True)
class TemplateMatch:
    profile: TemplateProfile
    confidence: float


def detect_template(
    inspection: WorkbookInspection,
    profiles: tuple[TemplateProfile, ...],
) -> TemplateMatch | None:
    matches: list[TemplateMatch] = []
    for profile in profiles:
        total_weight = sum(anchor.weight for anchor in profile.anchors)
        matched_weight = 0.0
        rejected = False
        for anchor in profile.anchors:
            matched = _anchor_matches(inspection, anchor)
            if anchor.required and not matched:
                rejected = True
                break
            if matched:
                matched_weight += anchor.weight
        if rejected or total_weight <= 0:
            continue
        confidence = matched_weight / total_weight
        if confidence >= profile.minimum_confidence:
            matches.append(TemplateMatch(profile=profile, confidence=confidence))
    return max(matches, key=lambda result: result.confidence, default=None)


def _anchor_matches(
    inspection: WorkbookInspection,
    anchor: CellAnchor,
) -> bool:
    sheet = inspection.sheet(anchor.sheet)
    if sheet is None:
        return False
    if anchor.coordinate is None:
        return True
    cell = sheet.cell(anchor.coordinate)
    if cell is None:
        return False
    if anchor.expected is None:
        return cell.value is not None
    actual = str(cell.value).strip().casefold()
    expected = anchor.expected.strip().casefold()
    if anchor.match is AnchorMatch.CONTAINS:
        return expected in actual
    if anchor.match is AnchorMatch.STARTS_WITH:
        return actual.startswith(expected)
    return actual == expected


__all__ = [
    "AnchorMatch",
    "CellAnchor",
    "TemplateMatch",
    "TemplateProfile",
    "detect_template",
]
