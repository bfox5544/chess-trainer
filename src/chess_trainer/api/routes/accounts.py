from typing import Annotated

from fastapi import APIRouter, Query, status
from sqlalchemy import select

from chess_trainer.api.deps import AccountDep, SessionDep
from chess_trainer.api.schemas import AnalyzeRequest, GameOut, ImportRequest, JobAccepted
from chess_trainer.db.enums import JobKind
from chess_trainer.db.models import AccountGame, Game
from chess_trainer.jobs import queue

router = APIRouter(prefix="/accounts", tags=["accounts"])


@router.post(
    "/{account_id}/import", response_model=JobAccepted, status_code=status.HTTP_202_ACCEPTED
)
def import_games(body: ImportRequest, account: AccountDep, session: SessionDep) -> JobAccepted:
    """Queue an import of the account's recent games (and, by default, their
    analysis). Poll `GET /jobs/{job_id}` for progress."""
    params: dict[str, object] = {
        "account_id": account.id,
        "time_classes": [tc.value for tc in body.time_classes] if body.time_classes else None,
        "max_games": body.max_games,
        "since": body.since.isoformat() if body.since else None,
        "analyze": body.analyze,
        "depth": body.depth,
    }
    return JobAccepted(job_id=queue.enqueue(session, JobKind.IMPORT, params).id)


@router.post(
    "/{account_id}/analyze", response_model=JobAccepted, status_code=status.HTTP_202_ACCEPTED
)
def analyze(body: AnalyzeRequest, account: AccountDep, session: SessionDep) -> JobAccepted:
    """Queue analysis of the account's stored games. Games already analyzed
    at this depth (or deeper) by the same engine are skipped."""
    params: dict[str, object] = {"account_id": account.id, "depth": body.depth}
    return JobAccepted(job_id=queue.enqueue(session, JobKind.ANALYZE, params).id)


@router.get("/{account_id}/games", response_model=list[GameOut])
def games(
    account: AccountDep,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[Game]:
    """The account's stored games, newest first."""
    stmt = (
        select(Game)
        .join(AccountGame, AccountGame.game_id == Game.id)
        .where(AccountGame.account_id == account.id)
        .order_by(Game.played_at.desc().nulls_last(), Game.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(session.scalars(stmt))
