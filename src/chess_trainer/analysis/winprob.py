"""Engine evaluations and their conversion to win probability.

Mistakes are measured in win-probability points rather than centipawns:
dropping from +8 to +5 loses three pawns of evaluation but almost no winning
chances, while dropping from +1 to -2 changes the likely result of the game.

The curve is the one Lichess fitted to real games:
    win% = 50 + 50 * (2 / (1 + exp(-0.00368208 * cp)) - 1)
"""

import math
from dataclasses import dataclass

import chess

LICHESS_COEFFICIENT = -0.00368208
# Beyond +-10 pawns the curve is flat; Lichess clamps here too.
CP_CLAMP = 1000
# A checkmate already on the board has no "mate in N" (N would be 0, which
# cannot carry a sign), so it is stored as this centipawn sentinel instead.
CHECKMATE_CP = 100_000


@dataclass(frozen=True)
class Eval:
    """An evaluation from White's point of view. Exactly one field is set.

    `mate` is the signed distance to mate: +3 means White mates in 3,
    -2 means Black mates in 2.
    """

    cp: int | None = None
    mate: int | None = None

    def __post_init__(self) -> None:
        if (self.cp is None) == (self.mate is None):
            raise ValueError("Eval needs exactly one of cp or mate")
        if self.mate == 0:
            raise ValueError("use Eval.checkmate() for a mate already on the board")

    @classmethod
    def draw(cls) -> "Eval":
        return cls(cp=0)

    @classmethod
    def checkmate(cls, winner: chess.Color) -> "Eval":
        return cls(cp=CHECKMATE_CP if winner == chess.WHITE else -CHECKMATE_CP)

    def is_mate_for(self, color: chess.Color) -> bool:
        """Does `color` have a forced (or delivered) mate?"""
        sign = 1 if color == chess.WHITE else -1
        if self.mate is not None:
            return self.mate * sign > 0
        return self.cp is not None and self.cp * sign >= CHECKMATE_CP


def white_win_pct(evaluation: Eval) -> float:
    """White's winning chances, 0-100."""
    if evaluation.mate is not None:
        return 100.0 if evaluation.mate > 0 else 0.0
    cp = evaluation.cp or 0
    if abs(cp) >= CHECKMATE_CP:
        return 100.0 if cp > 0 else 0.0
    clamped = max(-CP_CLAMP, min(CP_CLAMP, cp))
    return 50 + 50 * (2 / (1 + math.exp(LICHESS_COEFFICIENT * clamped)) - 1)


def win_pct(evaluation: Eval, color: chess.Color) -> float:
    """Winning chances for `color`, 0-100.

    The single place where White's point of view is flipped. Everything else
    stores White-POV evals and calls this.
    """
    white = white_win_pct(evaluation)
    return white if color == chess.WHITE else 100.0 - white
