"""XLSX inspection and template detection."""

from .fingerprint import (
    AnchorMatch,
    CellAnchor,
    TemplateMatch,
    TemplateProfile,
    detect_template,
)
from .inspector import WorkbookInspectionError, WorkbookInspector

__all__ = [
    "AnchorMatch",
    "CellAnchor",
    "TemplateMatch",
    "TemplateProfile",
    "WorkbookInspectionError",
    "WorkbookInspector",
    "detect_template",
]
