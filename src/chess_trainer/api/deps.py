"""FastAPI dependencies."""

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session

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
