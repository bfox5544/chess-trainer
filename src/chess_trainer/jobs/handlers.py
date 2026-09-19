"""What each job kind actually does.

Handlers are plain functions of (session, job, context). Nothing here knows
about the queue's polling loop, so moving to another job runner later means
writing new wrappers, not rewriting this logic.
"""

import logging
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from datetime import datetime
from typing import IO

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from chess_trainer.analysis.cache import EvalCache, Evaluator, get_or_create_engine_config
from chess_trainer.analysis.classify import Thresholds
from chess_trainer.analysis.engine import Engine
from chess_trainer.analysis.highlights import HIGHLIGHTS_VERSION, HighlightConfig
from chess_trainer.analysis.openings import OpeningBook
from chess_trainer.analysis.pipeline import analyze_game, mark_highlights
from chess_trainer.config import Settings
from chess_trainer.db.enums import JobKind, Platform, TimeClass
from chess_trainer.db.models import AccountGame, ChessAccount, Game, Job
from chess_trainer.ingestion.service import import_games
from chess_trainer.ingestion.sources import FetchFilters, GameSource
from chess_trainer.jobs import queue
from chess_trainer.library.feed import open_lines
from chess_trainer.library.parse import RowFilter
from chess_trainer.library.store import import_library
from chess_trainer.puzzles.generator import generate_puzzles_for_game, puzzle_config_from

logger = logging.getLogger(__name__)


@dataclass
class JobContext:
    """Everything handlers need from the outside world, injectable for tests."""

    settings: Settings
    build_source: Callable[[Platform], GameSource]
    # Called lazily so a worker that only imports never starts Stockfish.
    get_engine: Callable[[], Engine]
    book: OpeningBook
    # Opens the Lichess puzzle CSV; None means `settings.puzzle_library_source`.
    open_puzzle_library: Callable[[], AbstractContextManager[IO[str]]] | None = field(default=None)

    def puzzle_library_lines(self) -> AbstractContextManager[IO[str]]:
        if self.open_puzzle_library is not None:
            return self.open_puzzle_library()
        return open_lines(
            self.settings.puzzle_library_source,
            user_agent=self.settings.http_user_agent,
            timeout=self.settings.http_timeout_seconds,
        )


def thresholds_from(settings: Settings) -> Thresholds:
    return Thresholds(
        settings.inaccuracy_threshold, settings.mistake_threshold, settings.blunder_threshold
    )


def highlight_config_from(settings: Settings) -> HighlightConfig:
    return HighlightConfig(
        great_gap=settings.great_gap,
        min_sacrifice=settings.brilliant_min_sacrifice,
        max_loss=settings.brilliant_max_loss,
        min_win_pct_after=settings.highlight_min_win_pct_after,
        max_win_pct_before=settings.highlight_max_win_pct_before,
    )


def filters_from(params: dict[str, object]) -> FetchFilters:
    time_classes = params.get("time_classes")
    since = params.get("since")
    return FetchFilters(
        time_classes=frozenset(TimeClass(tc) for tc in time_classes) if time_classes else None,  # type: ignore[union-attr]
        max_games=int(params.get("max_games", 50)),  # type: ignore[call-overload]
        since=datetime.fromisoformat(since) if isinstance(since, str) else None,
    )


def run_import(session: Session, job: Job, context: JobContext) -> dict[str, object]:
    """Import an account's games, then queue their analysis as a child job."""
    account = session.get_one(ChessAccount, job.params["account_id"])
    source = context.build_source(account.platform)
    result = import_games(session, account, source, filters_from(job.params))
    session.commit()
    summary = result.as_dict()
    # An automatic sync that found nothing new has nothing to analyze.
    nothing_new = job.params.get("auto") and not result.stored
    if job.params.get("analyze", True) and not nothing_new:
        child = queue.enqueue(
            session,
            JobKind.ANALYZE,
            {"account_id": account.id, "depth": job.params.get("depth")},
            parent_id=job.id,
        )
        session.commit()
        summary["analyze_job_id"] = child.id
    return summary


def games_needing_analysis(
    session: Session, account_id: int, depth: int, engine_config_id: int
) -> list[Game]:
    """Games not yet analyzed at this depth by a compatible engine."""
    stmt = (
        select(Game)
        .join(AccountGame, AccountGame.game_id == Game.id)
        .where(
            AccountGame.account_id == account_id,
            or_(
                Game.analyzed_depth.is_(None),
                Game.analyzed_depth < depth,
                Game.analysis_engine_config_id != engine_config_id,
            ),
        )
        .order_by(Game.played_at.desc().nulls_last(), Game.id)
    )
    return list(session.scalars(stmt))


def games_needing_highlights(session: Session, account_id: int, skip: set[int]) -> list[Game]:
    """Analyzed games not yet checked for great and brilliant moves under the
    current rules (analyzed before the check existed, or before a rule change)."""
    stmt = (
        select(Game)
        .join(AccountGame, AccountGame.game_id == Game.id)
        .where(
            AccountGame.account_id == account_id,
            Game.analyzed_depth.is_not(None),
            or_(Game.highlights_version.is_(None), Game.highlights_version < HIGHLIGHTS_VERSION),
        )
        .order_by(Game.played_at.desc().nulls_last(), Game.id)
    )
    return [game for game in session.scalars(stmt) if game.id not in skip]


def run_analyze(session: Session, job: Job, context: JobContext) -> dict[str, object]:
    """Analyze every game of an account that still needs it.

    Commits after each game, so a crash loses at most one game of work and a
    re-run resumes where it stopped.
    """
    settings = context.settings
    depth = int(job.params.get("depth") or settings.analysis_depth)  # type: ignore[call-overload]
    engine = context.get_engine()
    config = get_or_create_engine_config(session, engine)
    evaluator = Evaluator(engine, EvalCache(session, config.id))
    account_id = int(job.params["account_id"])  # type: ignore[call-overload]
    games = games_needing_analysis(session, account_id, depth, config.id)
    # Games analyzed before great and brilliant moves existed only need that check.
    to_check = games_needing_highlights(session, account_id, {game.id for game in games})
    work = [(game, True) for game in games] + [(game, False) for game in to_check]
    queue.report_progress(session, job, 0, len(work))
    failed: dict[str, str] = {}
    analyzed = checked = puzzles = highlights = 0
    for done, (game, full) in enumerate(work, start=1):
        try:
            # Savepoint: a game that fails rolls back alone.
            with session.begin_nested():
                if full:
                    found = analyze_and_make_puzzles(
                        session, game, evaluator, context, depth, config.id
                    )
                else:
                    found = GameFindings(0, check_highlights(session, game, evaluator, context))
            analyzed += full
            checked += not full
            puzzles += found.puzzles
            highlights += found.highlights
        except Exception as exc:
            logger.exception("analysis failed for game %s", game.id)
            failed[str(game.id)] = repr(exc)
        queue.report_progress(session, job, done)
    return {
        "analyzed": analyzed,
        "checked_for_highlights": checked,
        "failed": failed,
        "depth": depth,
        "puzzles_created": puzzles,
        "highlights": highlights,
    }


@dataclass(frozen=True)
class GameFindings:
    puzzles: int  # accepted
    highlights: int  # great and brilliant moves


def analyze_and_make_puzzles(
    session: Session,
    game: Game,
    evaluator: Evaluator,
    context: JobContext,
    depth: int,
    engine_config_id: int,
) -> GameFindings:
    """Analyze one game, mark its great and brilliant moves, then build
    puzzles from its mistakes."""
    settings = context.settings
    analyze_game(
        session, game, evaluator, context.book, depth, thresholds_from(settings), engine_config_id
    )
    highlights = check_highlights(session, game, evaluator, context)
    puzzles = generate_puzzles_for_game(
        session,
        game,
        evaluator,
        puzzle_config_from(settings),
        # Never validate puzzles more shallowly than the analysis that found them.
        max(depth, settings.effective_puzzle_depth),
        engine_config_id,
    )
    return GameFindings(puzzles, highlights)


def check_highlights(
    session: Session, game: Game, evaluator: Evaluator, context: JobContext
) -> int:
    """Mark an analyzed game's great and brilliant moves, at the depth it was
    analyzed at."""
    config = highlight_config_from(context.settings)
    depth = game.analyzed_depth or context.settings.analysis_depth
    return mark_highlights(session, game, evaluator, config, depth)


def run_puzzle_library(session: Session, job: Job, context: JobContext) -> dict[str, object]:
    """Load (or refresh) puzzles from the Lichess puzzle database."""
    settings = context.settings
    limit = job.params.get("limit")
    limit = int(limit) if limit is not None else None  # type: ignore[call-overload]
    row_filter = RowFilter(
        min_popularity=settings.puzzle_library_min_popularity,
        min_plays=settings.puzzle_library_min_plays,
    )
    queue.report_progress(session, job, 0, limit)
    with context.puzzle_library_lines() as lines:
        result = import_library(
            session,
            lines,
            limit=limit,
            row_filter=row_filter,
            batch_size=settings.puzzle_library_batch_size,
            on_progress=lambda stored: queue.report_progress(session, job, stored),
        )
    return result.as_dict()


HANDLERS: dict[JobKind, Callable[[Session, Job, JobContext], dict[str, object]]] = {
    JobKind.IMPORT: run_import,
    JobKind.ANALYZE: run_analyze,
    JobKind.PUZZLE_LIBRARY: run_puzzle_library,
}
