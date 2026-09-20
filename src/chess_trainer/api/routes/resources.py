"""Routes addressed by their own id: jobs, games, puzzles."""

from fastapi import APIRouter, HTTPException, status

from chess_trainer.api.deps import SessionDep, SettingsDep
from chess_trainer.api.schemas import (
    GameOut,
    GameReportOut,
    JobOut,
    JobSummary,
    KeyMomentOut,
    LastMoveOut,
    MoveOut,
    PuzzleDetailOut,
    ReasonOut,
    StatsOut,
)
from chess_trainer.db.enums import PuzzleStatus
from chess_trainer.db.models import Job, Puzzle
from chess_trainer.jobs import queue
from chess_trainer.reports.game_report import build_game_report, explain_ply, move_at
from chess_trainer.reports.key_moments import KeyMomentConfig

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
def game_analysis(game_id: int, session: SessionDep, settings: SettingsDep) -> GameReportOut:
    """Every move with its classification and a plain-language explanation,
    plus per-side totals. `moves` is empty (and `game.analyzed_depth` null)
    until the game has been analyzed."""
    config = KeyMomentConfig(settings.key_moments_max, settings.key_moment_min_swing)
    report = build_game_report(session, game_id, config)
    if report is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"game {game_id} not found")
    moves = [
        MoveOut.model_validate(move).model_copy(
            update={"explanation": [ReasonOut.model_validate(r) for r in reasons]}
        )
        for move, reasons in zip(report.moves, report.explanations, strict=True)
    ]
    return GameReportOut(
        game=GameOut.model_validate(report.game),
        white=StatsOut.model_validate(report.white),
        black=StatsOut.model_validate(report.black),
        moves=moves,
        key_moments=[KeyMomentOut.model_validate(moment) for moment in report.key_moments],
    )


@router.get("/puzzles/{puzzle_id}", response_model=PuzzleDetailOut, tags=["puzzles"])
def puzzle(puzzle_id: int, session: SessionDep) -> PuzzleDetailOut:
    """Everything a client needs to present and check a puzzle: the start
    position, the opponent's move that led to it, whose move it is, the full
    solution line, and why the move played in the game was a mistake."""
    found = session.get(Puzzle, puzzle_id)
    if found is None or found.status is not PuzzleStatus.ACCEPTED:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"puzzle {puzzle_id} not found")
    reasons = explain_ply(session, found.game_id, found.ply)
    previous = move_at(session, found.game_id, found.ply - 1)
    return PuzzleDetailOut.model_validate(found).model_copy(
        update={
            "explanation": [ReasonOut.model_validate(r) for r in reasons],
            "last_move": LastMoveOut.model_validate(previous) if previous else None,
        }
    )
