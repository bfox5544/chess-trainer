"""Worker process: `uv run chess-trainer-worker`.

Polls the jobs table and runs one job at a time. Run several processes to
analyze in parallel; `SKIP LOCKED` keeps them from colliding.
"""

import logging
import time
from collections.abc import Callable

from sqlalchemy.orm import Session

from chess_trainer.analysis.engine import Engine, StockfishEngine
from chess_trainer.analysis.openings import load_opening_book
from chess_trainer.config import Settings, get_settings
from chess_trainer.db.models import Job
from chess_trainer.db.session import get_sessionmaker
from chess_trainer.ingestion.factory import build_source
from chess_trainer.jobs import queue
from chess_trainer.jobs.handlers import HANDLERS, JobContext

logger = logging.getLogger(__name__)


def run_job(session: Session, job: Job, context: JobContext) -> None:
    """Run one claimed job and record success or failure on its row."""
    try:
        result = HANDLERS[job.kind](session, job, context)
    except Exception as exc:
        session.rollback()
        logger.exception("job %s failed", job.id)
        queue.fail(session, job, f"{type(exc).__name__}: {exc}")
    else:
        queue.finish(session, job, result)


def work_once(session: Session, context: JobContext) -> bool:
    """Claim and run a single job. Returns False if the queue was empty."""
    job = queue.claim_next(session)
    if job is None:
        return False
    logger.info("running job %s (%s)", job.id, job.kind)
    run_job(session, job, context)
    return True


class LazyEngine:
    """Starts Stockfish on first use and keeps it for the worker's lifetime."""

    def __init__(self, factory: Callable[[], StockfishEngine]) -> None:
        self._factory = factory
        self._engine: StockfishEngine | None = None

    def get(self) -> Engine:
        if self._engine is None:
            self._engine = self._factory()
        return self._engine

    def close(self) -> None:
        if self._engine is not None:
            self._engine.close()


def stockfish_factory(settings: Settings) -> Callable[[], StockfishEngine]:
    return lambda: StockfishEngine(
        settings.stockfish_path,
        settings.engine_threads,
        settings.engine_hash_mb,
        settings.engine_eval_file,
    )


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    settings = get_settings()
    engine = LazyEngine(stockfish_factory(settings))
    context = JobContext(
        settings=settings,
        build_source=lambda platform: build_source(platform, settings),
        get_engine=engine.get,
        book=load_opening_book(),
    )
    logger.info("worker started; polling every %ss", settings.worker_poll_seconds)
    try:
        with get_sessionmaker()() as session:
            while True:
                queue.requeue_stale(session, settings.job_stale_seconds)
                if not work_once(session, context):
                    time.sleep(settings.worker_poll_seconds)
    except KeyboardInterrupt:
        logger.info("worker stopping")
    finally:
        engine.close()


if __name__ == "__main__":
    main()
