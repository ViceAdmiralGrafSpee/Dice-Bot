"""Shared authoritative action for D&D 5e (2014) checks."""

from __future__ import annotations

from dataclasses import dataclass

from src.chat.actions import ActionContext, ActionResult

from .engine import D20RollMode, Dnd5eEngine


@dataclass(frozen=True, slots=True)
class Dnd5eCheckRequest:
    mode: D20RollMode = D20RollMode.NORMAL
    modifier: int = 0


@dataclass(slots=True)
class Dnd5eCheckAction:
    """Resolve and serialize one check for every external adapter."""

    engine: Dnd5eEngine

    async def execute(
        self,
        request: Dnd5eCheckRequest,
        _context: ActionContext,
    ) -> ActionResult:
        result = self.engine.check(
            modifier=request.modifier,
            mode=request.mode,
        )
        return ActionResult(
            data={
                "ruleset": "dnd5e",
                "mode": result.mode.value,
                "rolls": list(result.rolls),
                "selected_roll": result.selected_roll,
                "modifier": result.modifier,
                "total": result.total,
            },
            authoritative_output=result.format(),
        )
