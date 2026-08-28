"""Turn a platform PGN into the columns we store, or a reason to skip it."""

import io
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

import chess.pgn

from chess_trainer.db.enums import Platform, TimeClass
from chess_trainer.ingestion.sources import RawGame
from chess_trainer.ingestion.timecontrol import parse_time_control
from chess_trainer.opening_names import family_of

# Aborted games and instant resignations teach nothing and skew statistics.
MIN_PLIES = 4
STANDARD_VARIANTS = {"", "standard", "chess"}


class SkipReason(StrEnum):
    UNPARSEABLE = "unparseable"
    VARIANT = "variant"
    CUSTOM_START = "custom_start"
    TOO_SHORT = "too_short"


@dataclass(frozen=True)
class NormalizedGame:
    platform: Platform
    platform_game_id: str
    pgn: str
    played_at: datetime | None
    white_username: str
    black_username: str
    white_rating: int | None
    black_rating: int | None
    result: str
    time_class: TimeClass
    base_seconds: int | None
    increment_seconds: int | None
    ply_count: int
    eco: str | None
    opening_name: str | None
    opening_family: str | None


def normalize(raw: RawGame) -> NormalizedGame | SkipReason:
    game = chess.pgn.read_game(io.StringIO(raw.pgn))
    if game is None:
        return SkipReason.UNPARSEABLE
    headers = game.headers
    # Variant checks come first: variant moves often look illegal under
    # standard rules, and "variant" is the more useful reason to report.
    if headers.get("Variant", "").lower() == "from position" or "FEN" in headers:
        return SkipReason.CUSTOM_START
    if headers.get("Variant", "").lower() not in STANDARD_VARIANTS:
        return SkipReason.VARIANT
    if game.errors:
        return SkipReason.UNPARSEABLE
    ply_count = sum(1 for _ in game.mainline_moves())
    if ply_count < MIN_PLIES:
        return SkipReason.TOO_SHORT
    return _build(raw, headers, ply_count)


def _build(raw: RawGame, headers: chess.pgn.Headers, ply_count: int) -> NormalizedGame:
    time_control = parse_time_control(headers.get("TimeControl"))
    opening_name = parse_opening_name(headers)
    return NormalizedGame(
        platform=raw.platform,
        platform_game_id=raw.platform_game_id,
        pgn=raw.pgn,
        played_at=parse_played_at(headers),
        white_username=headers.get("White", "?"),
        black_username=headers.get("Black", "?"),
        white_rating=parse_rating(headers.get("WhiteElo")),
        black_rating=parse_rating(headers.get("BlackElo")),
        result=headers.get("Result", "*"),
        time_class=time_control.time_class,
        base_seconds=time_control.base_seconds,
        increment_seconds=time_control.increment_seconds,
        ply_count=ply_count,
        eco=parse_eco(headers.get("ECO")),
        opening_name=opening_name,
        opening_family=family_of(opening_name),
    )


def parse_rating(raw: str | None) -> int | None:
    """'1500' -> 1500; '?' or missing -> None; tolerates '1500?' (provisional)."""
    digits = (raw or "").rstrip("?")
    return int(digits) if digits.isdigit() else None


def parse_eco(raw: str | None) -> str | None:
    return raw if raw and raw != "?" else None


def parse_played_at(headers: chess.pgn.Headers) -> datetime | None:
    date = headers.get("UTCDate") or headers.get("Date") or ""
    time_of_day = headers.get("UTCTime") or "00:00:00"
    try:
        return datetime.strptime(f"{date} {time_of_day}", "%Y.%m.%d %H:%M:%S").replace(tzinfo=UTC)
    except ValueError:
        return None  # e.g. '????.??.??'


def parse_opening_name(headers: chess.pgn.Headers) -> str | None:
    """Lichess sends `Opening`; Chess.com only sends an `ECOUrl` slug.

    The slug is a rough fallback. Analysis later replaces it with the name
    from the bundled opening book so both platforms use the same names.
    """
    opening = headers.get("Opening")
    if opening and opening != "?":
        return opening
    slug = headers.get("ECOUrl", "").rstrip("/").split("/")[-1]
    return slug.replace("-", " ") or None
