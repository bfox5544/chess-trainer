"""Builders for platform API payloads, shaped like the real responses."""

import json
import re
from typing import Any


def header(pgn: str, name: str) -> str:
    match = re.search(rf'\[{name} "([^"]*)"\]', pgn)
    assert match, f"PGN has no {name} header"
    return match.group(1)


def lichess_ndjson(pgns: list[str]) -> str:
    """Body of GET /api/games/user/{name} with pgnInJson=true."""
    lines = [json.dumps({"id": header(pgn, "Site").rsplit("/", 1)[-1], "pgn": pgn}) for pgn in pgns]
    return "\n".join(lines) + "\n"


def chesscom_game(pgn: str, end_time: int, rules: str = "chess") -> dict[str, Any]:
    """One entry of a Chess.com monthly archive."""
    url = header(pgn, "Link")
    return {
        "url": url,
        "uuid": f"uuid-{url.rsplit('/', 1)[-1]}",
        "pgn": pgn,
        "time_control": header(pgn, "TimeControl"),
        "end_time": end_time,
        "rules": rules,
    }
