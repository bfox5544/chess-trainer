"""Users and their linked platform accounts."""

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from chess_trainer.db.enums import Platform
from chess_trainer.db.models import ChessAccount, User


class AccountAlreadyLinked(Exception):
    """The platform account is already linked (to this or another user)."""


def create_user(session: Session, display_name: str) -> User:
    user = User(display_name=display_name)
    session.add(user)
    session.flush()
    return user


def link_account(session: Session, user: User, platform: Platform, username: str) -> ChessAccount:
    account = ChessAccount(user_id=user.id, platform=platform, username=username.strip().lower())
    try:
        # Savepoint so a duplicate doesn't poison the caller's transaction.
        with session.begin_nested():
            session.add(account)
            session.flush()
    except IntegrityError as exc:
        raise AccountAlreadyLinked(f"{platform.value}/{username} is already linked") from exc
    return account


def list_accounts(session: Session, user_id: int) -> list[ChessAccount]:
    stmt = select(ChessAccount).where(ChessAccount.user_id == user_id).order_by(ChessAccount.id)
    return list(session.scalars(stmt))
