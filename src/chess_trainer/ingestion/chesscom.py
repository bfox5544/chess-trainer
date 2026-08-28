"""Chess.com published-data API: https://www.chess.com/news/view/published-data-api

Games are grouped into monthly archives. We list the archives, then walk them
newest-first and stop as soon as enough games are collected, so a player with
years of history costs only a couple of requests.
"""

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

from chess_trainer.db.enums import Platform
from chess_trainer.ingestion.errors import PlayerNotFound, ResourceNotFound
from chess_trainer.ingestion.http import RetryingClient
from chess_trainer.ingestion.sources import FetchFilters, RawGame
from chess_trainer.ingestion.timecontrol import parse_time_control


def archive_month(archive_url: str) -> tuple[int, int]:
    """'.../games/2024/03' -> (2024, 3)."""
    year, month = archive_url.rstrip("/").split("/")[-2:]
    return int(year), int(month)


def is_wanted(game: dict[str, Any], filters: FetchFilters) -> bool:
    """Standard chess, has a PGN, matches the time-class and date filters."""
    if game.get("rules", "chess") != "chess" or not game.get("pgn"):
        return False
    if not filters.wants(parse_time_control(game.get("time_control")).time_class):
        return False
    if filters.since is not None and "end_time" in game:
        return datetime.fromtimestamp(game["end_time"], UTC) > filters.since
    return True


class ChessComSource:
    platform = Platform.CHESSCOM

    def __init__(self, http: RetryingClient, base_url: str = "https://api.chess.com") -> None:
        self._http = http
        self._base_url = base_url.rstrip("/")

    def fetch_games(self, username: str, filters: FetchFilters) -> Iterator[RawGame]:
        remaining = filters.max_games
        for archive_url in self._archives_newest_first(username, filters):
            if remaining <= 0:
                return  # checked before the request so no archive is fetched needlessly
            wanted = [g for g in self._games_newest_first(archive_url) if is_wanted(g, filters)]
            for game in wanted[:remaining]:
                yield self._to_raw(game)
            remaining -= len(wanted)

    def _archives_newest_first(self, username: str, filters: FetchFilters) -> list[str]:
        url = f"{self._base_url}/pub/player/{username.lower()}/games/archives"
        try:
            archives: list[str] = self._http.get(url).json().get("archives", [])
        except ResourceNotFound as exc:
            raise PlayerNotFound(f"Chess.com user '{username}' not found") from exc
        if filters.since is not None:
            cutoff = (filters.since.year, filters.since.month)
            archives = [a for a in archives if archive_month(a) >= cutoff]
        return sorted(archives, key=archive_month, reverse=True)

    def _games_newest_first(self, archive_url: str) -> list[dict[str, Any]]:
        games: list[dict[str, Any]] = self._http.get(archive_url).json().get("games", [])
        return sorted(games, key=lambda g: g.get("end_time", 0), reverse=True)

    @staticmethod
    def _to_raw(game: dict[str, Any]) -> RawGame:
        game_id = game.get("uuid") or game["url"].rstrip("/").split("/")[-1]
        return RawGame(Platform.CHESSCOM, str(game_id), game["pgn"])
