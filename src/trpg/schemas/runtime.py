"""Ruleset-provided character schema definitions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


FieldType = Literal["string", "integer", "number", "boolean", "object", "array"]


@dataclass(frozen=True, slots=True)
class CharacterFieldDefinition:
    path: str
    value_type: FieldType
    required: bool = False
    aliases: tuple[str, ...] = ()
    recommended_minimum: int | float | None = None
    recommended_maximum: int | float | None = None


@dataclass(frozen=True, slots=True)
class CharacterSchema:
    ruleset_key: str
    version: int
    fields: tuple[CharacterFieldDefinition, ...]

    def field(self, path: str) -> CharacterFieldDefinition | None:
        return next((field for field in self.fields if field.path == path), None)


__all__ = ["CharacterFieldDefinition", "CharacterSchema", "FieldType"]
