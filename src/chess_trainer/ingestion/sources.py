"""The contract every game source (Lichess, Chess.com, ...) implements."""

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from chess_trainer.db.enums import Platform, TimeClass


@dataclass(frozen=True)
class RawGame:
    """A game exactly as the platform returned it: an id and a PGN."""

    platform: Platform
    platform_game_id: str
    pgn: str


@dataclass(frozen=True)
class FetchFilters:
    time_classes: frozenset[TimeClass] | None = None  # None = all
    max_games: int = 50
    since: datetime | None = None

    def wants(self, time_class: TimeClass) -> bool:
        return self.time_classes is None or time_class in self.time_classes


class GameSource(Protocol):
    platform: Platform

    def fetch_games(self, username: str, filters: FetchFilters) -> Iterator[RawGame]:
        """Yield the user's most recent standard-chess games, newest first."""
        ...
