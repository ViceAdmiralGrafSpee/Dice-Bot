"""Parse and execute bounded tabletop dice expressions in Python."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import re
import secrets


MAX_DICE_COUNT = 100
MAX_DIE_SIDES = 100_000
MAX_ABS_MODIFIER = 1_000_000
_EXPRESSION_PATTERN = re.compile(
    r"^(?P<count>\d*)[dD](?P<sides>\d+)(?P<modifier>[+-]\d+)?$"
)


class DiceExpressionError(ValueError):
    """A user-facing validation error for a dice expression."""


@dataclass(frozen=True, slots=True)
class DiceRollResult:
    notation: str
    rolls: tuple[int, ...]
    modifier: int
    total: int

    def format(self) -> str:
        roll_text = ", ".join(str(value) for value in self.rolls)
        calculation = f"[{roll_text}]"
        if self.modifier > 0:
            calculation += f" + {self.modifier}"
        elif self.modifier < 0:
            calculation += f" - {abs(self.modifier)}"
        return f"🎲 {self.notation} = {calculation} = {self.total}"


class DiceEngine:
    """Roll dice with injectable randomness for deterministic tests."""

    def __init__(self, roll_die: Callable[[int], int] | None = None) -> None:
        self._roll_die = roll_die or self._secure_roll

    @staticmethod
    def _secure_roll(sides: int) -> int:
        return secrets.randbelow(sides) + 1

    def roll(self, expression: str) -> DiceRollResult:
        normalized = "".join(expression.split())
        match = _EXPRESSION_PATTERN.fullmatch(normalized)
        if match is None:
            raise DiceExpressionError("格式应类似 1d100 或 2d6+3")

        count = int(match.group("count") or "1")
        sides = int(match.group("sides"))
        modifier = int(match.group("modifier") or "0")

        if not 1 <= count <= MAX_DICE_COUNT:
            raise DiceExpressionError(f"一次只能骰 1～{MAX_DICE_COUNT} 颗骰子")
        if not 2 <= sides <= MAX_DIE_SIDES:
            raise DiceExpressionError(f"骰子面数必须在 2～{MAX_DIE_SIDES} 之间")
        if abs(modifier) > MAX_ABS_MODIFIER:
            raise DiceExpressionError(
                f"加减值的绝对值不能超过 {MAX_ABS_MODIFIER}"
            )

        rolls = tuple(self._roll_die(sides) for _ in range(count))
        if any(value < 1 or value > sides for value in rolls):
            raise RuntimeError("随机数生成器返回了超出骰子范围的结果")

        notation = f"{count}d{sides}"
        if modifier > 0:
            notation += f"+{modifier}"
        elif modifier < 0:
            notation += str(modifier)
        return DiceRollResult(
            notation=notation,
            rolls=rolls,
            modifier=modifier,
            total=sum(rolls) + modifier,
        )
