"""FastAPI dependencies."""

import threading
from collections.abc import Callable, Iterator
from functools import lru_cache
from typing import Annotated

from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session

from chess_trainer.analysis.engine import Engine, StockfishEngine
from chess_trainer.config import Settings, get_settings
from chess_trainer.db.models import ChessAccount, User
from chess_trainer.db.session import get_sessionmaker


def get_session() -> Iterator[Session]:
    """One session per request, committed if the handler returns normally."""
    with get_sessionmaker()() as session:
        yield session
        session.commit()


SessionDep = Annotated[Session, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


def load_user(user_id: int, session: SessionDep) -> User:
    """Resolve the user a request is about.

    There is no authentication yet. This is the single seam for it: when auth
    arrives, check here that the caller is allowed to act as `user_id`.
    """
    user = session.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"user {user_id} not found")
    return user


def load_account(account_id: int, session: SessionDep) -> ChessAccount:
    account = session.get(ChessAccount, account_id)
    if account is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"account {account_id} not found")
    return account


UserDep = Annotated[User, Depends(load_user)]
AccountDep = Annotated[ChessAccount, Depends(load_account)]


class SharedEngine:
    """One engine for the API process, for scoring moves live. Started on
    first use (most requests never need it) and used by one request at a
    time: a UCI engine searches one position at a time."""

    def __init__(self, factory: Callable[[], Engine]) -> None:
        self._factory = factory
        self._engine: Engine | None = None
        self.lock = threading.Lock()

    def get(self) -> Engine:
        """Call with `lock` held."""
        if self._engine is None:
            self._engine = self._factory()
        return self._engine

    def discard(self) -> None:
        """Forget a crashed engine so the next request starts a new one."""
        self._engine = None


@lru_cache
def get_shared_engine() -> SharedEngine:
    settings = get_settings()
    return SharedEngine(
        lambda: StockfishEngine(
            settings.stockfish_path,
            settings.engine_threads,
            settings.engine_hash_mb,
            settings.engine_eval_file,
        )
    )


EngineDep = Annotated[SharedEngine, Depends(get_shared_engine)]
