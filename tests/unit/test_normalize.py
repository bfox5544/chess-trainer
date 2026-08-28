from collections.abc import Callable
from datetime import UTC, datetime

from chess_trainer.db.enums import Platform, TimeClass
from chess_trainer.ingestion.normalize import (
    NormalizedGame,
    SkipReason,
    normalize,
    parse_rating,
)
from chess_trainer.ingestion.sources import RawGame


def raw(platform: Platform, pgn: str) -> RawGame:
    return RawGame(platform, "game-1", pgn)


def test_lichess_game(load_pgn: Callable[[str], str]) -> None:
    game = normalize(raw(Platform.LICHESS, load_pgn("lichess_scholars_mate")))
    assert isinstance(game, NormalizedGame)
    assert game.white_username == "alice_attacker"
    assert game.black_username == "BobLearner"
    assert (game.white_rating, game.black_rating) == (1510, 1480)
    assert game.result == "1-0"
    assert game.played_at == datetime(2024, 3, 10, 18, 30, tzinfo=UTC)
    assert game.time_class is TimeClass.BLITZ
    assert (game.base_seconds, game.increment_seconds) == (300, 0)
    assert game.ply_count == 7
    assert (game.eco, game.opening_name, game.opening_family) == (
        "C23",
        "Bishop's Opening",
        "Bishop's Opening",
    )


def test_chesscom_game_takes_opening_from_url_slug(load_pgn: Callable[[str], str]) -> None:
    game = normalize(raw(Platform.CHESSCOM, load_pgn("chesscom_opera_game")))
    assert isinstance(game, NormalizedGame)
    assert game.time_class is TimeClass.RAPID
    assert game.ply_count == 33
    assert game.eco == "C41"
    assert game.opening_name == "Philidor Defense 3.d4 Bg4"


def test_daily_game_is_correspondence(load_pgn: Callable[[str], str]) -> None:
    game = normalize(raw(Platform.CHESSCOM, load_pgn("chesscom_daily_no_clock")))
    assert isinstance(game, NormalizedGame)
    assert game.time_class is TimeClass.CORRESPONDENCE
    assert game.base_seconds is None


def test_variant_is_skipped(load_pgn: Callable[[str], str]) -> None:
    assert normalize(raw(Platform.LICHESS, load_pgn("lichess_chess960"))) is SkipReason.VARIANT


def test_aborted_game_is_skipped(load_pgn: Callable[[str], str]) -> None:
    assert normalize(raw(Platform.LICHESS, load_pgn("lichess_aborted"))) is SkipReason.TOO_SHORT


def test_custom_start_position_is_skipped() -> None:
    pgn = '[FEN "8/8/8/8/8/4k3/8/4K3 w - - 0 1"]\n[SetUp "1"]\n\n1. Kd1 Kd3 2. Ke1 Ke3 *'
    assert normalize(raw(Platform.LICHESS, pgn)) is SkipReason.CUSTOM_START


def test_illegal_moves_are_unparseable() -> None:
    pgn = '[White "a"]\n[Black "b"]\n\n1. e4 e5 2. Ke3 Qh4 *'
    assert normalize(raw(Platform.LICHESS, pgn)) is SkipReason.UNPARSEABLE


def test_unknown_rating_is_none() -> None:
    assert parse_rating("?") is None
    assert parse_rating(None) is None
    assert parse_rating("1500?") == 1500
