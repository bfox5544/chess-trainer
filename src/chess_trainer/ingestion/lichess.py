"""Lichess game export: https://lichess.org/api#tag/Games/operation/apiGamesUser"""

import json
from collections.abc import Iterator
from typing import Any

from chess_trainer.db.enums import Platform, TimeClass
from chess_trainer.ingestion.errors import PlayerNotFound, ResourceNotFound
from chess_trainer.ingestion.http import RetryingClient
from chess_trainer.ingestion.sources import FetchFilters, RawGame

# Lichess "perf types" for each of our time classes. Always sending an
# explicit list also keeps variants (Chess960, ...) out of the `max` budget.
PERF_TYPES: dict[TimeClass, tuple[str, ...]] = {
    TimeClass.BULLET: ("ultraBullet", "bullet"),
    TimeClass.BLITZ: ("blitz",),
    TimeClass.RAPID: ("rapid",),
    TimeClass.CLASSICAL: ("classical",),
    TimeClass.CORRESPONDENCE: ("correspondence",),
}


def perf_type_param(time_classes: frozenset[TimeClass] | None) -> str:
    wanted = [tc for tc in PERF_TYPES if time_classes is None or tc in time_classes]
    return ",".join(perf for tc in wanted for perf in PERF_TYPES[tc])


class LichessSource:
    platform = Platform.LICHESS

    def __init__(self, http: RetryingClient, base_url: str = "https://lichess.org") -> None:
        self._http = http
        self._base_url = base_url.rstrip("/")

    def fetch_games(self, username: str, filters: FetchFilters) -> Iterator[RawGame]:
        url = f"{self._base_url}/api/games/user/{username}"
        headers = {"Accept": "application/x-ndjson"}
        try:
            # Streamed: the endpoint emits one JSON game per line, newest first.
            with self._http.stream(url, params=self._params(filters), headers=headers) as resp:
                for line in resp.iter_lines():
                    if line.strip():
                        yield self._to_raw(json.loads(line))
        except ResourceNotFound as exc:
            raise PlayerNotFound(f"Lichess user '{username}' not found") from exc

    @staticmethod
    def _params(filters: FetchFilters) -> dict[str, str]:
        params = {
            "max": str(filters.max_games),
            "perfType": perf_type_param(filters.time_classes),
            "pgnInJson": "true",
            "clocks": "true",
            "opening": "true",
        }
        if filters.since is not None:
            params["since"] = str(int(filters.since.timestamp() * 1000))
        return params

    @staticmethod
    def _to_raw(data: dict[str, Any]) -> RawGame:
        return RawGame(Platform.LICHESS, str(data["id"]), data["pgn"])
