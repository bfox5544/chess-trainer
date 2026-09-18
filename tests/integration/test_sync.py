from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from chess_trainer.config import Settings
from chess_trainer.db.base import utcnow
from chess_trainer.db.enums import JobKind, JobStatus
from chess_trainer.db.models import ChessAccount, Game, Job
from chess_trainer.jobs import queue, scheduler
from chess_trainer.jobs.handlers import JobContext
from chess_trainer.jobs.worker import work_once

pytestmark = pytest.mark.integration


def test_never_imported_accounts_are_not_synced(
    session: Session, bob: ChessAccount, settings: Settings
) -> None:
    assert bob.last_synced_at is None
    assert scheduler.schedule_syncs(session, settings, utcnow()) == []


def test_accounts_are_synced_once_the_interval_has_passed(
    session: Session, scholars_game: Game, bob: ChessAccount, settings: Settings
) -> None:
    now = utcnow()
    assert scheduler.schedule_syncs(session, settings, now) == []  # just imported

    later = now + timedelta(minutes=settings.auto_sync_minutes + 1)
    (job,) = scheduler.schedule_syncs(session, settings, later)
    assert job.kind is JobKind.IMPORT and job.params["auto"] is True
    assert job.params["account_id"] == bob.id
    assert job.params["max_games"] == settings.auto_sync_max_games
    # fetched from a day before the newest stored game
    assert scholars_game.played_at is not None
    expected = scholars_game.played_at - scheduler.SINCE_OVERLAP
    assert job.params["since"] == expected.isoformat()

    # queued once, not again on the next check, even if it fails
    job.created_at = later  # the job was queued on the simulated clock
    session.flush()
    assert scheduler.schedule_syncs(session, settings, later) == []
    queue.fail(session, job, "SourceUnavailable: down")
    assert scheduler.schedule_syncs(session, settings, later + timedelta(minutes=1)) == []


def test_sync_can_be_turned_off(session: Session, scholars_game: Game, settings: Settings) -> None:
    off = settings.model_copy(update={"auto_sync_minutes": 0})
    assert scheduler.schedule_syncs(session, off, utcnow() + timedelta(days=1)) == []


def test_a_sync_with_nothing_new_queues_no_analysis(
    session: Session, scholars_game: Game, bob: ChessAccount, job_context: JobContext
) -> None:
    params = {"account_id": bob.id, "auto": True}
    job = queue.enqueue(session, JobKind.IMPORT, params)
    assert work_once(session, job_context) is True
    assert job.status is JobStatus.SUCCEEDED and job.result is not None
    assert job.result["stored"] == 0
    assert queue.children_of(session, job.id) == []


def test_sync_status_reports_an_import_being_analyzed(
    client: TestClient, session: Session, bob: ChessAccount, job_context: JobContext
) -> None:
    url = f"/users/{bob.user_id}/sync"
    assert client.get(url).json() == {"interval_minutes": 15.0, "active_job_id": None}

    job = queue.enqueue(session, JobKind.IMPORT, {"account_id": bob.id, "auto": True})
    work_once(session, job_context)  # stores the game and queues its analysis
    assert client.get(url).json()["active_job_id"] == job.id

    (analysis,) = queue.children_of(session, job.id)
    queue.finish(session, session.get_one(Job, analysis.id))
    assert client.get(url).json()["active_job_id"] is None
