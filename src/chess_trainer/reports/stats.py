"""Counting helpers shared by the game report and the weakness report."""

import math
from collections.abc import Iterable
from dataclasses import dataclass

from chess_trainer.db.enums import Classification


def move_accuracy(win_pct_loss: float) -> float:
    """Accuracy of one move, 0-100, from the win-probability points it lost.

    Lichess's fitted curve: a move that loses nothing scores 100, losing 10
    points scores about 64, losing 30 about 25.
    """
    return max(0.0, min(100.0, 103.1668 * math.exp(-0.04354 * win_pct_loss) - 3.1669))


@dataclass(frozen=True)
class MoveStats:
    moves: int
    inaccuracies: int
    mistakes: int
    blunders: int
    # Mean win-probability points given away per move.
    average_win_pct_loss: float
    # Mistakes + blunders per 100 moves: comparable across buckets of any size.
    errors_per_100_moves: float
    # Mean per-move accuracy, 0-100. Simpler than Lichess's game accuracy
    # (which also weights by how volatile the position was), so numbers will
    # not match theirs exactly.
    accuracy: float


def summarize(moves: Iterable[tuple[Classification, float]]) -> MoveStats:
    """Summarize (classification, win_pct_loss) pairs."""
    pairs = list(moves)
    count = len(pairs)
    tally = {label: sum(1 for c, _ in pairs if c is label) for label in Classification}
    errors = tally[Classification.MISTAKE] + tally[Classification.BLUNDER]
    return MoveStats(
        moves=count,
        inaccuracies=tally[Classification.INACCURACY],
        mistakes=tally[Classification.MISTAKE],
        blunders=tally[Classification.BLUNDER],
        average_win_pct_loss=round(sum(loss for _, loss in pairs) / count, 2) if count else 0.0,
        errors_per_100_moves=round(100 * errors / count, 1) if count else 0.0,
        accuracy=(
            round(sum(move_accuracy(loss) for _, loss in pairs) / count, 1) if count else 0.0
        ),
    )
