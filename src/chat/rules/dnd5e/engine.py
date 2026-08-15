"""Small, authoritative D&D 5e (2014) d20 check engine."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
import secrets


MAX_ABS_CHECK_MODIFIER = 1_000_000

MIN_ABILITY_SCORE = 1
MAX_ABILITY_SCORE = 30


def ability_modifier(ability_score: int) -> int:
    """Authoritative D&D 5e ability modifier: floor((score - 10) / 2).

    Python's integer floor division handles negative scores correctly,
    for example 9 -> -1, 7 -> -2. Callers must validate the score range.
    """
    return (ability_score - 10) // 2


class Dnd5eCheckError(ValueError):
    """A user-facing validation error for a D&D 5e check."""


class D20RollMode(str, Enum):
    NORMAL = "normal"
    ADVANTAGE = "advantage"
    DISADVANTAGE = "disadvantage"


@dataclass(frozen=True, slots=True)
class D20CheckResult:
    mode: D20RollMode
    rolls: tuple[int, ...]
    selected_roll: int
    modifier: int
    total: int

    def format(self) -> str:
        mode_name = {
            D20RollMode.NORMAL: "普通",
            D20RollMode.ADVANTAGE: "优势",
            D20RollMode.DISADVANTAGE: "劣势",
        }[self.mode]
        rolls_text = ", ".join(str(value) for value in self.rolls)
        calculation = f"[{rolls_text}]"
        if self.mode is not D20RollMode.NORMAL:
            calculation += f" → {self.selected_roll}"
        if self.modifier > 0:
            calculation += f" + {self.modifier}"
        elif self.modifier < 0:
            calculation += f" - {abs(self.modifier)}"
        return f"🎲 DND 5e {mode_name}检定：{calculation} = {self.total}"


class Dnd5eEngine:
    """Resolve d20 checks in Python with injectable randomness for tests."""

    def __init__(self, roll_d20: Callable[[], int] | None = None) -> None:
        self._roll_d20 = roll_d20 or self._secure_roll_d20

    @staticmethod
    def _secure_roll_d20() -> int:
        return secrets.randbelow(20) + 1

    def check(
        self,
        modifier: int = 0,
        mode: D20RollMode = D20RollMode.NORMAL,
    ) -> D20CheckResult:
        if abs(modifier) > MAX_ABS_CHECK_MODIFIER:
            raise Dnd5eCheckError(
                f"加减值的绝对值不能超过 {MAX_ABS_CHECK_MODIFIER}"
            )

        roll_count = 1 if mode is D20RollMode.NORMAL else 2
        rolls = tuple(self._roll_d20() for _ in range(roll_count))
        if any(value < 1 or value > 20 for value in rolls):
            raise RuntimeError("随机数生成器返回了超出 d20 范围的结果")

        if mode is D20RollMode.ADVANTAGE:
            selected_roll = max(rolls)
        elif mode is D20RollMode.DISADVANTAGE:
            selected_roll = min(rolls)
        else:
            selected_roll = rolls[0]

        return D20CheckResult(
            mode=mode,
            rolls=rolls,
            selected_roll=selected_roll,
            modifier=modifier,
            total=selected_roll + modifier,
        )
