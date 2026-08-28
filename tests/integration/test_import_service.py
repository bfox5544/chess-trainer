from collections.abc import Callable, Iterator

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from chess_trainer.accounts.service import AccountAlreadyLinked, create_user, link_account
from chess_trainer.db.enums import Color, Platform
from chess_trainer.db.models import AccountGame, ChessAccount, Game
from chess_trainer.ingestion.service import import_games
from chess_trainer.ingestion.sources import FetchFilters, RawGame

pytestmark = pytest.mark.integration


class StubSource:
    """A GameSource that replays fixed games, so no HTTP is involved."""

    platform = Platform.LICHESS

    def __init__(self, games: list[RawGame]) -> None:
        self._games = games

    def fetch_games(self, username: str, filters: FetchFilters) -> Iterator[RawGame]:
        yield from self._games[: filters.max_games]


@pytest.fixture
def bob(session: Session) -> ChessAccount:
    user = create_user(session, "Bob")
    return link_account(session, user, Platform.LICHESS, "BobLearner")


@pytest.fixture
def source(load_pgn: Callable[[str], str]) -> StubSource:
    names = ["lichess_scholars_mate", "lichess_chess960", "lichess_aborted"]
    return StubSource([RawGame(Platform.LICHESS, f"id-{name}", load_pgn(name)) for name in names])


def count(session: Session, model: type) -> int:
    return session.scalar(select(func.count()).select_from(model)) or 0


def test_import_stores_games_and_reports_skips(
    session: Session, bob: ChessAccount, source: StubSource
) -> None:
    result = import_games(session, bob, source, FetchFilters())

    assert (result.fetched, result.stored, result.already_stored) == (3, 1, 0)
    assert dict(result.skipped) == {"variant": 1, "too_short": 1}
    game = session.scalars(select(Game)).one()
    assert game.black_username == "BobLearner"
    link = session.scalars(select(AccountGame)).one()
    assert (link.account_id, link.game_id, link.color) == (bob.id, game.id, Color.BLACK)
    assert bob.last_synced_at is not None


def test_reimport_skips_games_already_stored(
    session: Session, bob: ChessAccount, source: StubSource
) -> None:
    import_games(session, bob, source, FetchFilters())
    second = import_games(session, bob, source, FetchFilters())

    assert (second.stored, second.already_stored) == (0, 1)
    assert count(session, Game) == 1
    assert count(session, AccountGame) == 1


def test_game_between_two_tracked_accounts_is_stored_once(
    session: Session, bob: ChessAccount, source: StubSource
) -> None:
    alice_user = create_user(session, "Alice")
    alice = link_account(session, alice_user, Platform.LICHESS, "alice_attacker")

    import_games(session, bob, source, FetchFilters())
    import_games(session, alice, source, FetchFilters())

    assert count(session, Game) == 1
    colors = {link.account_id: link.color for link in session.scalars(select(AccountGame))}
    assert colors == {bob.id: Color.BLACK, alice.id: Color.WHITE}


def test_games_the_account_did_not_play_are_skipped(session: Session, source: StubSource) -> None:
    user = create_user(session, "Stranger")
    stranger = link_account(session, user, Platform.LICHESS, "not_in_these_games")
    result = import_games(session, stranger, source, FetchFilters())
    assert result.stored == 0
    assert result.skipped["not_a_participant"] == 1


def test_account_usernames_are_lowercased_and_unique(session: Session, bob: ChessAccount) -> None:
    assert bob.username == "boblearner"
    other = create_user(session, "Other")
    with pytest.raises(AccountAlreadyLinked):
        link_account(session, other, Platform.LICHESS, "BOBLEARNER")
    # The failed insert must not have broken the session.
    assert count(session, ChessAccount) == 1
