"""Routes addressed by their own id: jobs, games, puzzles."""

from fastapi import APIRouter, HTTPException, status

from chess_trainer.api.deps import SessionDep
from chess_trainer.api.schemas import GameReportOut, JobOut, JobSummary, PuzzleOut
from chess_trainer.db.enums import PuzzleStatus
from chess_trainer.db.models import Job, Puzzle
from chess_trainer.jobs import queue
from chess_trainer.reports.game_report import GameReport, build_game_report

router = APIRouter()


@router.get("/jobs/{job_id}", response_model=JobOut, tags=["jobs"])
def job_status(job_id: int, session: SessionDep) -> JobOut:
    job = session.get(Job, job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"job {job_id} not found")
    children = [JobSummary.model_validate(child) for child in queue.children_of(session, job.id)]
    summary = JobSummary.model_validate(job).model_dump()
    return JobOut(**summary, params=job.params, parent_id=job.parent_id, children=children)


@router.get("/games/{game_id}/analysis", response_model=GameReportOut, tags=["games"])
def game_analysis(game_id: int, session: SessionDep) -> GameReport:
    """Every move with its classification, plus per-side totals. `moves` is
    empty (and `game.analyzed_depth` null) until the game has been analyzed."""
    report = build_game_report(session, game_id)
    if report is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"game {game_id} not found")
    return report


@router.get("/puzzles/{puzzle_id}", response_model=PuzzleOut, tags=["puzzles"])
def puzzle(puzzle_id: int, session: SessionDep) -> Puzzle:
    """Everything a client needs to present and check a puzzle: the start
    position, whose move it is, and the full solution line."""
    found = session.get(Puzzle, puzzle_id)
    if found is None or found.status is not PuzzleStatus.ACCEPTED:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"puzzle {puzzle_id} not found")
    return found
