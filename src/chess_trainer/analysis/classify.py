"""Classify a move by how much winning chance it gave away."""

from dataclasses import dataclass

import chess

from chess_trainer.analysis.winprob import Eval, win_pct
from chess_trainer.db.enums import Classification


@dataclass(frozen=True)
class Thresholds:
    """Minimum win-probability points lost for each label (Lichess's values)."""

    inaccuracy: float = 5.0
    mistake: float = 10.0
    blunder: float = 15.0


def win_pct_loss(
    before: Eval, after: Eval, mover: chess.Color, *, played_best: bool, forced: bool
) -> float:
    """Win-probability points the mover lost with this move (never negative).

    `before` is the eval of the position the mover faced (i.e. after best
    play); `after` is the eval once their move was on the board.

    - Playing the engine's first choice costs nothing by definition. Without
      this rule, the two positions being searched separately would invent
      small phantom losses (and gains).
    - A forced move (only one legal option) cannot be an error.
    - A negative loss means the deeper look after the move liked the position
      more than the look before it: search noise, clamped to zero.
    """
    if played_best or forced:
        return 0.0
    return max(0.0, win_pct(before, mover) - win_pct(after, mover))


def classify(loss: float, thresholds: Thresholds) -> Classification:
    if loss >= thresholds.blunder:
        return Classification.BLUNDER
    if loss >= thresholds.mistake:
        return Classification.MISTAKE
    if loss >= thresholds.inaccuracy:
        return Classification.INACCURACY
    return Classification.GOOD
