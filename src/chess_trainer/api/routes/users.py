from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status

from chess_trainer.accounts.service import AccountAlreadyLinked, create_user, link_account
from chess_trainer.api.deps import SessionDep, SettingsDep, UserDep
from chess_trainer.api.schemas import (
    AccountCreate,
    AccountOut,
    PuzzleOut,
    UserCreate,
    UserOut,
    WeaknessReportOut,
)
from chess_trainer.db.enums import Classification, Phase, PuzzleOutcome, TimeClass
from chess_trainer.db.models import ChessAccount, Puzzle, User
from chess_trainer.puzzles.service import PuzzleFilters, list_puzzles
from chess_trainer.reports.weakness import WeaknessFilters, WeaknessReport, build_weakness_report

router = APIRouter(prefix="/users", tags=["users"])


@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create(body: UserCreate, session: SessionDep) -> User:
    return create_user(session, body.display_name)


@router.get("/{user_id}", response_model=UserOut)
def get(user: UserDep) -> User:
    return user


@router.post("/{user_id}/accounts", response_model=AccountOut, status_code=status.HTTP_201_CREATED)
def add_account(body: AccountCreate, user: UserDep, session: SessionDep) -> ChessAccount:
    """Link a Lichess or Chess.com account. The username is checked against
    the platform when games are first imported, not here."""
    try:
        return link_account(session, user, body.platform, body.username)
    except AccountAlreadyLinked as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc


@router.get("/{user_id}/report", response_model=WeaknessReportOut)
def weakness_report(
    user: UserDep,
    session: SessionDep,
    settings: SettingsDep,
    account_id: int | None = None,
    time_class: TimeClass | None = None,
    since: datetime | None = None,
) -> WeaknessReport:
    """Where the user loses winning chances, across all linked accounts."""
    filters = WeaknessFilters(account_id=account_id, time_class=time_class, since=since)
    return build_weakness_report(session, user.id, filters, settings)


@router.get("/{user_id}/puzzles", response_model=list[PuzzleOut])
def puzzles(
    user: UserDep,
    session: SessionDep,
    outcome: PuzzleOutcome | None = None,
    phase: Phase | None = None,
    severity: Classification | None = None,
    account_id: int | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[Puzzle]:
    """Puzzles built from the user's own mistakes, newest first."""
    filters = PuzzleFilters(outcome=outcome, phase=phase, severity=severity, account_id=account_id)
    return list_puzzles(session, user.id, filters, limit, offset)
