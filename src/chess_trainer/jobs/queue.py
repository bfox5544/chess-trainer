"""Postgres-backed job queue: the `jobs` table is the queue.

`FOR UPDATE SKIP LOCKED` lets several workers poll the same table without
ever claiming the same job, with no broker to run. See README for the
trade-off against Celery.
"""

from datetime import timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from chess_trainer.db.base import utcnow
from chess_trainer.db.enums import JobKind, JobStatus
from chess_trainer.db.models import Job


def enqueue(
    session: Session, kind: JobKind, params: dict[str, object], parent_id: int | None = None
) -> Job:
    job = Job(kind=kind, params=params, parent_id=parent_id)
    session.add(job)
    session.flush()
    return job


def claim_next(session: Session) -> Job | None:
    """Atomically take the oldest queued job, or None if the queue is empty."""
    stmt = (
        select(Job)
        .where(Job.status == JobStatus.QUEUED)
        .order_by(Job.id)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    job = session.scalars(stmt).first()
    if job is None:
        return None
    job.status = JobStatus.RUNNING
    job.started_at = job.heartbeat_at = utcnow()
    session.commit()
    return job


def report_progress(session: Session, job: Job, done: int, total: int | None = None) -> None:
    job.progress_done = done
    if total is not None:
        job.progress_total = total
    job.heartbeat_at = utcnow()
    session.commit()


def finish(session: Session, job: Job, result: dict[str, object] | None = None) -> None:
    job.status = JobStatus.SUCCEEDED
    job.result = result
    job.finished_at = utcnow()
    session.commit()


def fail(session: Session, job: Job, error: str) -> None:
    job.status = JobStatus.FAILED
    job.error = error
    job.finished_at = utcnow()
    session.commit()


def requeue_stale(session: Session, stale_seconds: float) -> int:
    """Put jobs back on the queue whose worker stopped heartbeating (crashed).

    Safe because job handlers are resumable: an analysis job skips games that
    were already analyzed, and imports skip games already stored.
    """
    cutoff = utcnow() - timedelta(seconds=stale_seconds)
    stmt = (
        update(Job)
        .where(Job.status == JobStatus.RUNNING, Job.heartbeat_at < cutoff)
        .values(status=JobStatus.QUEUED, started_at=None)
    )
    count = session.execute(stmt).rowcount
    session.commit()
    return count


def children_of(session: Session, job_id: int) -> list[Job]:
    return list(session.scalars(select(Job).where(Job.parent_id == job_id).order_by(Job.id)))
