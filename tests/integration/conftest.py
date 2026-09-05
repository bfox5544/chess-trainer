from collections.abc import Callable, Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from chess_trainer.accounts.service import create_user, link_account
from chess_trainer.analysis.openings import load_opening_book
from chess_trainer.api.app import create_app
from chess_trainer.api.deps import get_session
from chess_trainer.config import Settings, get_settings
from chess_trainer.db.enums import Platform
from chess_trainer.db.models import ChessAccount, Game
from chess_trainer.ingestion.service import import_games
from chess_trainer.ingestion.sources import FetchFilters, RawGame
from chess_trainer.jobs.handlers import JobContext
from tests.fakes import FakeEngine, StubSource, scholars_mate_script


@pytest.fixture
def bob(session: Session) -> ChessAccount:
    """A user with one Lichess account, 'BobLearner'."""
    user = create_user(session, "Bob")
    return link_account(session, user, Platform.LICHESS, "BobLearner")


@pytest.fixture
def scholars_source(load_pgn: Callable[[str], str]) -> StubSource:
    return StubSource([RawGame(Platform.LICHESS, "abcd1234", load_pgn("lichess_scholars_mate"))])


@pytest.fixture
def scholars_game(session: Session, bob: ChessAccount, scholars_source: StubSource) -> Game:
    """The Scholar's Mate fixture imported for Bob (who plays Black)."""
    import_games(session, bob, scholars_source, FetchFilters())
    return session.query(Game).one()


@pytest.fixture
def engine() -> FakeEngine:
    return FakeEngine(scholars_mate_script())


@pytest.fixture
def job_context(settings: Settings, engine: FakeEngine, scholars_source: StubSource) -> JobContext:
    return JobContext(
        settings=settings,
        build_source=lambda platform: scholars_source,
        get_engine=lambda: engine,
        book=load_opening_book(),
    )


@pytest.fixture
def client(session: Session, settings: Settings) -> Iterator[TestClient]:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_settings] = lambda: settings
    with TestClient(app) as test_client:
        yield test_client
