from datetime import timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from chess_trainer.db.base import utcnow
from chess_trainer.db.enums import Classification, JobKind, JobStatus
from chess_trainer.db.models import ChessAccount, Game, Job, MoveAnalysis
from chess_trainer.ingestion.errors import PlayerNotFound
from chess_trainer.jobs import queue
from chess_trainer.jobs.handlers import JobContext
from chess_trainer.jobs.worker import work_once
from tests.fakes import FakeEngine

pytestmark = pytest.mark.integration


def test_jobs_are_claimed_oldest_first_and_only_once(session: Session) -> None:
    first = queue.enqueue(session, JobKind.IMPORT, {"account_id": 1})
    second = queue.enqueue(session, JobKind.IMPORT, {"account_id": 2})

    claimed = queue.claim_next(session)
    assert claimed is not None and claimed.id == first.id
    assert claimed.status is JobStatus.RUNNING and claimed.started_at is not None
    again = queue.claim_next(session)
    assert again is not None and again.id == second.id
    assert queue.claim_next(session) is None


def test_stale_running_jobs_are_requeued(session: Session) -> None:
    job = queue.enqueue(session, JobKind.ANALYZE, {})
    queue.claim_next(session)
    assert queue.requeue_stale(session, stale_seconds=600) == 0  # fresh heartbeat

    job.heartbeat_at = utcnow() - timedelta(hours=1)
    session.flush()
    assert queue.requeue_stale(session, stale_seconds=600) == 1
    session.refresh(job)
    assert job.status is JobStatus.QUEUED


def test_import_job_stores_games_then_queues_analysis(
    session: Session, bob: ChessAccount, job_context: JobContext
) -> None:
    job = queue.enqueue(session, JobKind.IMPORT, {"account_id": bob.id, "max_games": 10})

    assert work_once(session, job_context) is True

    assert job.status is JobStatus.SUCCEEDED
    assert job.result is not None and job.result["stored"] == 1
    (child,) = queue.children_of(session, job.id)
    assert child.kind is JobKind.ANALYZE and child.status is JobStatus.QUEUED
    assert job.result["analyze_job_id"] == child.id


def test_import_then_analyze_end_to_end(
    session: Session, bob: ChessAccount, job_context: JobContext, engine: FakeEngine
) -> None:
    queue.enqueue(session, JobKind.IMPORT, {"account_id": bob.id, "depth": 10})
    assert work_once(session, job_context)  # import
    assert work_once(session, job_context)  # analysis
    assert not work_once(session, job_context)  # queue drained

    analyze_job = session.scalars(select(Job).where(Job.kind == JobKind.ANALYZE)).one()
    assert analyze_job.status is JobStatus.SUCCEEDED
    assert (analyze_job.progress_done, analyze_job.progress_total) == (1, 1)
    assert analyze_job.result == {"analyzed": 1, "failed": {}, "depth": 10}
    assert session.scalars(select(Game)).one().analyzed_depth == 10
    blunders = session.scalars(
        select(MoveAnalysis).where(MoveAnalysis.classification == Classification.BLUNDER)
    ).all()
    assert [m.san for m in blunders] == ["Nf6"]


def test_analyze_job_skips_games_already_analyzed_deep_enough(
    session: Session, bob: ChessAccount, job_context: JobContext, engine: FakeEngine
) -> None:
    queue.enqueue(session, JobKind.IMPORT, {"account_id": bob.id, "depth": 12})
    work_once(session, job_context)
    work_once(session, job_context)
    engine.calls.clear()

    shallower = queue.enqueue(session, JobKind.ANALYZE, {"account_id": bob.id, "depth": 8})
    work_once(session, job_context)

    assert shallower.progress_total == 0 and engine.calls == []


def test_failed_job_records_the_error(
    session: Session, bob: ChessAccount, job_context: JobContext
) -> None:
    def missing_player(platform: object) -> object:
        raise PlayerNotFound("Lichess user 'boblearner' not found")

    job_context.build_source = missing_player  # type: ignore[assignment]
    job = queue.enqueue(session, JobKind.IMPORT, {"account_id": bob.id})

    work_once(session, job_context)

    assert job.status is JobStatus.FAILED
    assert job.error == "PlayerNotFound: Lichess user 'boblearner' not found"
    assert job.finished_at is not None


def test_one_bad_game_does_not_fail_the_whole_analysis_job(
    session: Session, bob: ChessAccount, scholars_game: Game, job_context: JobContext
) -> None:
    scholars_game.pgn = "this is not a game"
    job = queue.enqueue(session, JobKind.ANALYZE, {"account_id": bob.id})

    work_once(session, job_context)

    assert job.status is JobStatus.SUCCEEDED
    assert job.result is not None and job.result["analyzed"] == 0
    assert list(job.result["failed"]) == [str(scholars_game.id)]  # type: ignore[call-overload]
