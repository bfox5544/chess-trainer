"""Shared fixtures. Unit tests need none of the database fixtures below."""

from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from chess_trainer.config import Settings

ROOT = Path(__file__).parent.parent
PGN_DIR = Path(__file__).parent / "fixtures" / "pgn"


@pytest.fixture(scope="session")
def load_pgn() -> Callable[[str], str]:
    def _load(name: str) -> str:
        return (PGN_DIR / f"{name}.pgn").read_text()

    return _load


@pytest.fixture
def settings() -> Settings:
    """Defaults only: tests must not depend on the developer's .env."""
    return Settings(_env_file=None)


@pytest.fixture(scope="session")
def db_engine() -> Iterator[Engine]:
    """Migrated test database. Running the real migrations tests them too."""
    url = Settings().test_database_url
    engine = create_engine(url)
    try:
        with engine.begin() as connection:
            connection.execute(text("DROP SCHEMA public CASCADE"))
            connection.execute(text("CREATE SCHEMA public"))
    except OperationalError:
        pytest.skip("Postgres test database unavailable (run `docker compose up -d`)")
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", url)
    config.attributes["configure_logging"] = False
    command.upgrade(config, "head")
    yield engine
    engine.dispose()


@pytest.fixture
def session(db_engine: Engine) -> Iterator[Session]:
    """A session whose work is rolled back after each test.

    `create_savepoint` lets code under test call `commit()` freely: commits
    only release a savepoint inside the outer, never-committed transaction.
    """
    with db_engine.connect() as connection:
        transaction = connection.begin()
        with Session(
            connection, join_transaction_mode="create_savepoint", expire_on_commit=False
        ) as db_session:
            yield db_session
        transaction.rollback()
