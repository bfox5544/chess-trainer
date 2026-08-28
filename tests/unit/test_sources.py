"""Lichess and Chess.com clients against mocked HTTP (no network)."""

from collections.abc import Callable
from datetime import UTC, datetime

import httpx
import pytest
import respx

from chess_trainer.db.enums import Platform, TimeClass
from chess_trainer.ingestion.chesscom import ChessComSource
from chess_trainer.ingestion.errors import PlayerNotFound
from chess_trainer.ingestion.http import RetryingClient
from chess_trainer.ingestion.lichess import LichessSource, perf_type_param
from chess_trainer.ingestion.sources import FetchFilters
from tests.helpers import chesscom_game, lichess_ndjson

LICHESS_URL = "https://lichess.org/api/games/user/BobLearner"
ARCHIVES_URL = "https://api.chess.com/pub/player/boblearner/games/archives"
JAN = "https://api.chess.com/pub/player/boblearner/games/2024/01"
FEB = "https://api.chess.com/pub/player/boblearner/games/2024/02"


@pytest.fixture
def http() -> RetryingClient:
    return RetryingClient(httpx.Client(), max_retries=1, sleep=lambda _: None)


# --- Lichess ---------------------------------------------------------------


@respx.mock
def test_lichess_streams_games(http: RetryingClient, load_pgn: Callable[[str], str]) -> None:
    body = lichess_ndjson([load_pgn("lichess_scholars_mate"), load_pgn("lichess_aborted")])
    route = respx.get(LICHESS_URL).respond(text=body)

    games = list(LichessSource(http).fetch_games("BobLearner", FetchFilters(max_games=20)))

    assert [g.platform_game_id for g in games] == ["abcd1234", "short001"]
    assert games[0].platform is Platform.LICHESS
    assert "Qxf7#" in games[0].pgn
    request = route.calls.last.request
    assert request.headers["Accept"] == "application/x-ndjson"
    params = dict(request.url.params)
    assert params["max"] == "20"
    assert params["clocks"] == "true" and params["opening"] == "true"
    assert "since" not in params


@respx.mock
def test_lichess_sends_time_class_and_since_filters(http: RetryingClient) -> None:
    route = respx.get(LICHESS_URL).respond(text="")
    since = datetime(2024, 1, 1, tzinfo=UTC)
    filters = FetchFilters(time_classes=frozenset({TimeClass.BLITZ}), since=since)

    assert list(LichessSource(http).fetch_games("BobLearner", filters)) == []

    params = dict(route.calls.last.request.url.params)
    assert params["perfType"] == "blitz"
    assert params["since"] == str(int(since.timestamp() * 1000))


def test_lichess_perf_types_exclude_variants_and_fold_ultrabullet() -> None:
    assert perf_type_param(None) == "ultraBullet,bullet,blitz,rapid,classical,correspondence"
    assert perf_type_param(frozenset({TimeClass.BULLET})) == "ultraBullet,bullet"


@respx.mock
def test_lichess_unknown_user(http: RetryingClient) -> None:
    respx.get(LICHESS_URL).respond(404)
    with pytest.raises(PlayerNotFound):
        list(LichessSource(http).fetch_games("BobLearner", FetchFilters()))


# --- Chess.com -------------------------------------------------------------


def mock_archives(load_pgn: Callable[[str], str]) -> dict[str, respx.Route]:
    opera = chesscom_game(load_pgn("chesscom_opera_game"), end_time=1708460142)
    daily = chesscom_game(load_pgn("chesscom_daily_no_clock"), end_time=1704441600)
    variant = chesscom_game(load_pgn("chesscom_opera_game"), end_time=1708460999, rules="chess960")
    return {
        "archives": respx.get(ARCHIVES_URL).respond(json={"archives": [JAN, FEB]}),
        "jan": respx.get(JAN).respond(json={"games": [daily]}),
        "feb": respx.get(FEB).respond(json={"games": [opera, variant]}),
    }


@respx.mock
def test_chesscom_walks_archives_newest_first(
    http: RetryingClient, load_pgn: Callable[[str], str]
) -> None:
    mock_archives(load_pgn)
    games = list(ChessComSource(http).fetch_games("BobLearner", FetchFilters()))
    # February's game first, the chess960 game dropped, then January's.
    assert [g.platform_game_id for g in games] == ["uuid-1234567890", "uuid-555"]
    assert all(g.platform is Platform.CHESSCOM for g in games)


@respx.mock
def test_chesscom_stops_fetching_once_max_is_reached(
    http: RetryingClient, load_pgn: Callable[[str], str]
) -> None:
    routes = mock_archives(load_pgn)
    games = list(ChessComSource(http).fetch_games("BobLearner", FetchFilters(max_games=1)))
    assert len(games) == 1
    assert not routes["jan"].called  # older archive never requested


@respx.mock
def test_chesscom_filters_time_class_client_side(
    http: RetryingClient, load_pgn: Callable[[str], str]
) -> None:
    mock_archives(load_pgn)
    filters = FetchFilters(time_classes=frozenset({TimeClass.CORRESPONDENCE}))
    games = list(ChessComSource(http).fetch_games("BobLearner", filters))
    assert [g.platform_game_id for g in games] == ["uuid-555"]


@respx.mock
def test_chesscom_since_skips_old_archives(
    http: RetryingClient, load_pgn: Callable[[str], str]
) -> None:
    routes = mock_archives(load_pgn)
    filters = FetchFilters(since=datetime(2024, 2, 1, tzinfo=UTC))
    games = list(ChessComSource(http).fetch_games("BobLearner", filters))
    assert [g.platform_game_id for g in games] == ["uuid-1234567890"]
    assert not routes["jan"].called


@respx.mock
def test_chesscom_unknown_user(http: RetryingClient) -> None:
    respx.get(ARCHIVES_URL).respond(404)
    with pytest.raises(PlayerNotFound):
        list(ChessComSource(http).fetch_games("BobLearner", FetchFilters()))
