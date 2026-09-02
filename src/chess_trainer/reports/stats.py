"""Counting helpers shared by the game report and the weakness report."""

from collections.abc import Iterable
from dataclasses import dataclass

from chess_trainer.db.enums import Classification


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
    )
