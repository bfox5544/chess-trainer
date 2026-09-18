"""Automatic sync: the worker queues an import of each linked account's new
games every `auto_sync_minutes`.

Only accounts imported at least once are synced, so linking an account never
starts a large first import on its own. A sync is an ordinary import job
(flagged `auto`), so it shows up and fails like any other; an account is not
retried until the interval has passed again, even if its last sync failed.
"""

from datetime import datetime, timedelta

from sqlalchemy import Integer, func, select
from sqlalchemy.orm import Session

from chess_trainer.config import Settings
from chess_trainer.db.enums import JobKind, JobStatus
from chess_trainer.db.models import AccountGame, ChessAccount, Game, Job
from chess_trainer.jobs import queue

# Games are fetched from a little before the newest stored one: a game that
# finished just before the last sync may reach the platform's archive late.
# Duplicates are skipped by the import, so the overlap costs nothing.
SINCE_OVERLAP = timedelta(days=1)


def due_accounts(session: Session, now: datetime, interval: timedelta) -> list[ChessAccount]:
    """Accounts last synced more than `interval` ago, with no import job of
    any outcome queued in that time (so a failing account is not retried
    on every poll)."""
    cutoff = now - interval
    recent_import = (
        select(Job.id)
        .where(
            Job.kind == JobKind.IMPORT,
            Job.params["account_id"].astext.cast(Integer) == ChessAccount.id,
            Job.created_at > cutoff,
        )
        .exists()
    )
    stmt = (
        select(ChessAccount)
        .where(ChessAccount.last_synced_at.is_not(None), ChessAccount.last_synced_at < cutoff)
        .where(~recent_import)
        .order_by(ChessAccount.id)
    )
    return list(session.scalars(stmt))


def newest_game_at(session: Session, account_id: int) -> datetime | None:
    stmt = (
        select(func.max(Game.played_at))
        .join(AccountGame, AccountGame.game_id == Game.id)
        .where(AccountGame.account_id == account_id)
    )
    return session.scalar(stmt)


def sync_params(account: ChessAccount, newest: datetime | None, settings: Settings) -> dict:
    start = newest if newest is not None else account.last_synced_at
    return {
        "account_id": account.id,
        "time_classes": None,
        "max_games": settings.auto_sync_max_games,
        "since": (start - SINCE_OVERLAP).isoformat() if start else None,
        "analyze": True,
        "depth": None,
        "auto": True,
    }


def schedule_syncs(session: Session, settings: Settings, now: datetime) -> list[Job]:
    """Queue an import for every account that is due. Returns the new jobs."""
    if settings.auto_sync_minutes <= 0:
        return []
    interval = timedelta(minutes=settings.auto_sync_minutes)
    jobs = [
        queue.enqueue(
            session,
            JobKind.IMPORT,
            sync_params(account, newest_game_at(session, account.id), settings),
        )
        for account in due_accounts(session, now, interval)
    ]
    session.commit()
    return jobs


def active_import(session: Session, user_id: int) -> Job | None:
    """The newest import of the user's accounts whose analysis is queued or
    running. An import that brought nothing new has no analysis, so a
    routine sync is never reported."""
    analysis = (
        select(Job.parent_id)
        .join(ChessAccount, Job.params["account_id"].astext.cast(Integer) == ChessAccount.id)
        .where(
            ChessAccount.user_id == user_id,
            Job.kind == JobKind.ANALYZE,
            Job.status.in_([JobStatus.QUEUED, JobStatus.RUNNING]),
            Job.parent_id.is_not(None),
        )
        .order_by(Job.id.desc())
        .limit(1)
    )
    parent_id = session.scalar(analysis)
    return session.get(Job, parent_id) if parent_id is not None else None
