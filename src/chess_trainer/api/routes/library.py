"""The shared puzzle library, loaded from the Lichess puzzle database."""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select

from chess_trainer.api.deps import SessionDep
from chess_trainer.api.schemas import (
    JobAccepted,
    LibraryImportRequest,
    LibraryPuzzleOut,
    LibraryStepOut,
    LibrarySummaryOut,
    ThemeCountOut,
)
from chess_trainer.db.enums import JobKind, JobStatus
from chess_trainer.db.models import Job, LibraryPuzzle
from chess_trainer.jobs import queue
from chess_trainer.library.present import Step, trainer_line
from chess_trainer.library.store import (
    LibraryFilters,
    library_size,
    random_puzzle,
    random_puzzles,
    theme_counts,
)

router = APIRouter(prefix="/library", tags=["library"])


def step_out(step: Step) -> LibraryStepOut:
    return LibraryStepOut(uci=step.uci, san=step.san, by=step.by)


def puzzle_out(puzzle: LibraryPuzzle) -> LibraryPuzzleOut:
    try:
        line = trainer_line(puzzle.fen, puzzle.moves)
    except ValueError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, f"puzzle {puzzle.id} is invalid: {exc}"
        ) from exc
    return LibraryPuzzleOut(
        id=puzzle.id,
        fen=puzzle.fen,
        setup=step_out(line.setup),
        start_fen=line.start_fen,
        user_color=line.user_color,
        solution=[step_out(step) for step in line.solution],
        rating=puzzle.rating,
        rating_deviation=puzzle.rating_deviation,
        popularity=puzzle.popularity,
        nb_plays=puzzle.nb_plays,
        themes=puzzle.themes,
        game_url=puzzle.game_url,
        opening_tags=puzzle.opening_tags,
    )


@router.get("", response_model=LibrarySummaryOut)
def summary(session: SessionDep) -> LibrarySummaryOut:
    """How many puzzles are loaded, and how many carry each theme."""
    return LibrarySummaryOut(
        total=library_size(session),
        themes=[ThemeCountOut.model_validate(t) for t in theme_counts(session)],
    )


@router.post("/import", response_model=JobAccepted, status_code=status.HTTP_202_ACCEPTED)
def start_import(body: LibraryImportRequest, session: SessionDep) -> JobAccepted:
    """Queue a load of the Lichess puzzle database. If a load is already
    queued or running, returns that job instead of starting a second one."""
    running = session.scalars(
        select(Job).where(
            Job.kind == JobKind.PUZZLE_LIBRARY,
            Job.status.in_([JobStatus.QUEUED, JobStatus.RUNNING]),
        )
    ).first()
    if running is not None:
        return JobAccepted(job_id=running.id)
    job = queue.enqueue(session, JobKind.PUZZLE_LIBRARY, {"limit": body.limit})
    return JobAccepted(job_id=job.id)


@router.get("/puzzles", response_model=list[LibraryPuzzleOut])
def sample_library_puzzles(
    session: SessionDep,
    rating_min: Annotated[int | None, Query(ge=0, le=4000)] = None,
    rating_max: Annotated[int | None, Query(ge=0, le=4000)] = None,
    theme: Annotated[str | None, Query(max_length=40)] = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 12,
) -> list[LibraryPuzzleOut]:
    """A random sample of puzzles matching the filters (empty if none match).
    Each call returns a different sample."""
    found = random_puzzles(session, LibraryFilters(rating_min, rating_max, theme), limit)
    return [puzzle_out(puzzle) for puzzle in found]


@router.get("/puzzles/random", response_model=LibraryPuzzleOut)
def random_library_puzzle(
    session: SessionDep,
    rating_min: Annotated[int | None, Query(ge=0, le=4000)] = None,
    rating_max: Annotated[int | None, Query(ge=0, le=4000)] = None,
    theme: Annotated[str | None, Query(max_length=40)] = None,
    exclude: Annotated[
        str | None, Query(description="Comma-separated ids to skip (e.g. the current one)")
    ] = None,
) -> LibraryPuzzleOut:
    """A random puzzle matching the filters. 404 if none match (or the
    library is empty)."""
    skip = [item for item in (exclude or "").split(",") if item][:50]
    found = random_puzzle(session, LibraryFilters(rating_min, rating_max, theme), skip)
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no library puzzle matches these filters")
    return puzzle_out(found)


@router.get("/puzzles/{puzzle_id}", response_model=LibraryPuzzleOut)
def library_puzzle(puzzle_id: str, session: SessionDep) -> LibraryPuzzleOut:
    found = session.get(LibraryPuzzle, puzzle_id)
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"library puzzle {puzzle_id} not found")
    return puzzle_out(found)
