"""Extension point for tactical motif tagging (forks, pins, skewers, ...).

Nothing is registered yet. Detectors exist in `analysis/motifs.py` (they
drive puzzle recommendations) but are kept out of the registry until the
own-puzzle pages hide themes before solving. To add a motif:

1. Write a class with a `name` and a `tags()` method (see `MotifTagger`).
2. Append an instance to `REGISTRY`.

Puzzle generation already calls `tag_motifs()` and stores the result in
`puzzles.themes`, and the weakness report already groups by those themes, so
new taggers show up in both without further wiring. Existing puzzles can be
re-tagged from their stored `fen` and `solution`.
"""

from collections.abc import Sequence
from typing import Protocol

import chess


class MotifTagger(Protocol):
    name: str

    def tags(
        self, board: chess.Board, played: chess.Move, best_line: Sequence[chess.Move]
    ) -> set[str]:
        """Motifs present in `best_line` (the solution) from `board`.

        `played` is the move the player actually chose, for motifs that are
        about what was missed or allowed rather than what was available.
        """
        ...


REGISTRY: list[MotifTagger] = []


def tag_motifs(
    board: chess.Board, played: chess.Move, best_line: Sequence[chess.Move]
) -> list[str]:
    """Union of every registered tagger's motifs, sorted for stable storage."""
    found: set[str] = set()
    for tagger in REGISTRY:
        found |= tagger.tags(board, played, best_line)
    return sorted(found)
