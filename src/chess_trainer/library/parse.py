"""Parse the Lichess puzzle CSV. Pure: lines in, rows out.

Columns (the file has a header row; older dumps did not):
PuzzleId,FEN,Moves,Rating,RatingDeviation,Popularity,NbPlays,Themes,GameUrl,
OpeningTags[,DailyDate]

Validation here is cheap and structural (field shapes, move syntax). Full
legality is checked when a puzzle is served (`present.py`): replaying moves
for ~5 million rows at import time would multiply the import time for data
Lichess has already validated.
"""

import csv
import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass

LEGACY_FIELDS = (
    "PuzzleId",
    "FEN",
    "Moves",
    "Rating",
    "RatingDeviation",
    "Popularity",
    "NbPlays",
    "Themes",
    "GameUrl",
    "OpeningTags",
)
UCI = re.compile(r"^[a-h][1-8][a-h][1-8][qrbn]?$")
PUZZLE_ID = re.compile(r"^[A-Za-z0-9]{1,10}$")


@dataclass(frozen=True)
class LibraryRow:
    id: str
    fen: str
    moves: tuple[str, ...]
    rating: int
    rating_deviation: int
    popularity: int
    nb_plays: int
    themes: tuple[str, ...]
    game_url: str
    opening_tags: tuple[str, ...]


@dataclass(frozen=True)
class RowFilter:
    """Quality floor. Popularity is Lichess players' net vote (-100..100);
    puzzles with few plays have unsettled ratings."""

    min_popularity: int = -100
    min_plays: int = 0

    def accepts(self, row: LibraryRow) -> bool:
        return row.popularity >= self.min_popularity and row.nb_plays >= self.min_plays


def parse_record(record: dict[str, str]) -> LibraryRow | None:
    """One CSV record as a row, or None if it is malformed."""
    try:
        moves = tuple(record["Moves"].split())
        row = LibraryRow(
            id=record["PuzzleId"].strip(),
            fen=record["FEN"].strip(),
            moves=moves,
            rating=int(record["Rating"]),
            rating_deviation=int(record["RatingDeviation"]),
            popularity=int(record["Popularity"]),
            nb_plays=int(record["NbPlays"]),
            themes=tuple(record["Themes"].split()),
            game_url=record["GameUrl"].strip(),
            opening_tags=tuple((record.get("OpeningTags") or "").split()),
        )
    except (KeyError, ValueError, AttributeError):
        return None
    if not PUZZLE_ID.match(row.id) or len(row.fen.split()) != 6:
        return None
    # The first move is the opponent's; a puzzle needs at least one reply.
    if len(moves) < 2 or not all(UCI.match(move) for move in moves):
        return None
    return row


def read_records(lines: Iterable[str]) -> Iterator[dict[str, str]]:
    """CSV records, with or without a header row."""
    iterator = iter(lines)
    first = next(iterator, None)
    if first is None:
        return
    if first.startswith("PuzzleId"):
        yield from csv.DictReader(iterator, fieldnames=next(csv.reader([first])))
    else:
        yield from csv.DictReader(_chain(first, iterator), fieldnames=list(LEGACY_FIELDS))


def _chain(first: str, rest: Iterator[str]) -> Iterator[str]:
    yield first
    yield from rest
