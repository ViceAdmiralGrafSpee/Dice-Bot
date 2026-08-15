"""Shared authoritative action for D&D 5e (2014) checks."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.chat.actions import ActionContext, ActionResult

from .engine import (
    D20RollMode,
    Dnd5eCheckError,
    Dnd5eEngine,
    MAX_ABILITY_SCORE,
    MAX_ABS_CHECK_MODIFIER,
    MIN_ABILITY_SCORE,
    ability_modifier,
)


@dataclass(frozen=True, slots=True)
class Dnd5eCheckRequest:
    mode: D20RollMode = D20RollMode.NORMAL
    modifier: int | None = None
    ability_score: int | None = None
    proficiency_bonus: int | None = None
    misc_modifier: int | None = None


def _validate_optional_int(
    value: int | None,
    *,
    field_name: str,
) -> int | None:
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool):
        raise Dnd5eCheckError(f"{field_name} 必须是整数")
    return value


def _validate_ability_score(value: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise Dnd5eCheckError("ability_score 必须是整数")
    if value < MIN_ABILITY_SCORE or value > MAX_ABILITY_SCORE:
        raise Dnd5eCheckError(
            f"ability_score 必须在 {MIN_ABILITY_SCORE} 到 "
            f"{MAX_ABILITY_SCORE} 之间"
        )
    return value


def resolve_check_modifier(
    request: Dnd5eCheckRequest,
) -> tuple[int, dict[str, Any] | None]:
    """Determine the final d20 modifier from a request.

    Two mutually exclusive input styles are supported:

    - Direct modifier: the caller already computed the final total,
      e.g. ``modifier=6``. The payload stays identical to legacy usage.
    - Structured components: the caller provides the raw facts
      (``ability_score``, ``proficiency_bonus``, ``misc_modifier``) and
      Python computes the authoritative D&D 5e modifier. Only explicitly
      provided components are counted.

    Returns ``(modifier, breakdown_or_None)``. ``breakdown`` is only set
    for structured requests so legacy payloads stay byte-for-byte stable.
    """

    modifier = _validate_optional_int(request.modifier, field_name="modifier")
    ability_score = _validate_optional_int(
        request.ability_score, field_name="ability_score"
    )
    proficiency_bonus = _validate_optional_int(
        request.proficiency_bonus, field_name="proficiency_bonus"
    )
    misc_modifier = _validate_optional_int(
        request.misc_modifier, field_name="misc_modifier"
    )

    if modifier is not None and any(
        value is not None
        for value in (ability_score, proficiency_bonus, misc_modifier)
    ):
        raise Dnd5eCheckError(
            "modifier 与 ability_score/proficiency_bonus/misc_modifier "
            "不能同时提供"
        )

    if modifier is None and all(
        value is None
        for value in (ability_score, proficiency_bonus, misc_modifier)
    ):
        return 0, None

    if any(
        value is not None
        for value in (ability_score, proficiency_bonus, misc_modifier)
    ):
        if ability_score is not None:
            ability_score = _validate_ability_score(ability_score)
            score_modifier = ability_modifier(ability_score)
        else:
            score_modifier = 0
        final_modifier = (
            score_modifier
            + (proficiency_bonus or 0)
            + (misc_modifier or 0)
        )
        if abs(final_modifier) > MAX_ABS_CHECK_MODIFIER:
            raise Dnd5eCheckError(
                f"加减值的绝对值不能超过 {MAX_ABS_CHECK_MODIFIER}"
            )
        breakdown: dict[str, Any] = {
            "ability_score": ability_score,
            "ability_modifier": score_modifier,
            "proficiency_bonus": proficiency_bonus or 0,
            "misc_modifier": misc_modifier or 0,
        }
        return final_modifier, breakdown

    if abs(modifier) > MAX_ABS_CHECK_MODIFIER:
        raise Dnd5eCheckError(
            f"加减值的绝对值不能超过 {MAX_ABS_CHECK_MODIFIER}"
        )
    return modifier, None


@dataclass(slots=True)
class Dnd5eCheckAction:
    """Resolve and serialize one check for every external adapter."""

    engine: Dnd5eEngine

    async def execute(
        self,
        request: Dnd5eCheckRequest,
        _context: ActionContext,
    ) -> ActionResult:
        modifier, modifier_breakdown = resolve_check_modifier(request)
        result = self.engine.check(
            modifier=modifier,
            mode=request.mode,
        )
        data: dict[str, Any] = {
            "ruleset": "dnd5e",
            "mode": result.mode.value,
            "rolls": list(result.rolls),
            "selected_roll": result.selected_roll,
            "modifier": result.modifier,
            "total": result.total,
        }
        if modifier_breakdown is not None:
            data["modifier_breakdown"] = modifier_breakdown
        return ActionResult(
            data=data,
            authoritative_output=result.format(),
        )
