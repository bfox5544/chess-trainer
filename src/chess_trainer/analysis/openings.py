"""Opening lookup from the bundled Lichess openings dataset (CC0).

Lichess puts the opening name in the PGN; Chess.com only gives a URL slug.
Looking every game up in one dataset gives both platforms identical names,
which matters as soon as a report groups by opening.
"""

import csv
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources

import chess

from chess_trainer.opening_names import family_of


@dataclass(frozen=True)
class Opening:
    eco: str
    name: str

    @property
    def family(self) -> str:
        return family_of(self.name) or self.name


@dataclass(frozen=True)
class OpeningMatch:
    opening: Opening
    # Plies played to reach the deepest named position. Moves before this ply
    # are "book"; the first move after it is where the player left theory.
    ply: int


class OpeningBook:
    def __init__(self, by_epd: dict[str, Opening]) -> None:
        self._by_epd = by_epd

    def __len__(self) -> int:
        return len(self._by_epd)

    def lookup(self, board: chess.Board) -> Opening | None:
        return self._by_epd.get(board.epd())

    def deepest_match(self, boards: list[chess.Board]) -> OpeningMatch | None:
        """Last position of the game that is a named opening.

        `boards[i]` is the position after `i` plies. Scanning every position
        (rather than stopping at the first miss) handles transpositions that
        leave the book and re-enter it.
        """
        for ply in range(len(boards) - 1, 0, -1):
            opening = self.lookup(boards[ply])
            if opening is not None:
                return OpeningMatch(opening, ply)
        return None


@lru_cache
def load_opening_book() -> OpeningBook:
    data = resources.files("chess_trainer") / "data" / "openings.tsv"
    with data.open(newline="") as handle:
        rows = csv.DictReader(handle, delimiter="\t")
        return OpeningBook({row["epd"]: Opening(row["eco"], row["name"]) for row in rows})
