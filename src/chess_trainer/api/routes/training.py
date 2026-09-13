"""Personal training: a puzzle rating and library puzzles picked for the user."""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status

from chess_trainer.api.deps import SessionDep, SettingsDep, UserDep
from chess_trainer.api.routes.library import puzzle_out
from chess_trainer.api.schemas import (
    FocusOut,
    LibraryAttemptIn,
    LibraryAttemptOut,
    PuzzleRatingOut,
    RecommendationOut,
    TrainingProfileOut,
)
from chess_trainer.db.models import LibraryPuzzle
from chess_trainer.training.service import (
    AttemptResult,
    RatingState,
    TrainingProfile,
    build_profile,
    rating_state,
    recommend,
    record_attempt,
)

router = APIRouter(prefix="/users/{user_id}", tags=["training"])


@router.get("/puzzle-rating", response_model=PuzzleRatingOut)
def puzzle_rating(user: UserDep, session: SessionDep, settings: SettingsDep) -> RatingState:
    """The user's rating on the Lichess puzzle scale. Until a puzzle has been
    rated it is an estimate from their recent game ratings (`seeded`)."""
    return rating_state(session, user.id, settings)


@router.get("/training", response_model=TrainingProfileOut)
def training_profile(user: UserDep, session: SessionDep, settings: SettingsDep) -> TrainingProfile:
    """What the user should train and why: tactics they miss or allow, the
    openings they play, the phases where their mistakes happen, and their
    puzzle rating."""
    return build_profile(session, user.id, settings)


@router.get("/recommended-puzzles", response_model=list[RecommendationOut])
def recommended_puzzles(
    user: UserDep,
    session: SessionDep,
    settings: SettingsDep,
    limit: Annotated[int, Query(ge=1, le=30)] = 12,
    exclude: Annotated[str | None, Query(description="Comma-separated puzzle ids to skip")] = None,
) -> list[RecommendationOut]:
    """Library puzzles picked for the user, near their puzzle rating and not
    attempted before, each with the focus it trains. Every call picks anew.
    Empty if the library is empty."""
    skip = [item for item in (exclude or "").split(",") if item][:50]
    return [
        RecommendationOut(
            puzzle=puzzle_out(found.puzzle), focus=FocusOut.model_validate(found.focus)
        )
        for found in recommend(session, user.id, settings, limit, skip)
    ]


@router.post("/library-attempts", response_model=LibraryAttemptOut)
def add_library_attempt(
    body: LibraryAttemptIn, user: UserDep, session: SessionDep, settings: SettingsDep
) -> AttemptResult:
    """Record a finished attempt at a library puzzle. The first attempt at a
    puzzle moves the user's puzzle rating; repeats are stored unrated."""
    puzzle = session.get(LibraryPuzzle, body.puzzle_id)
    if puzzle is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"library puzzle {body.puzzle_id} not found")
    return record_attempt(
        session, user.id, puzzle, solved=body.solved, first_try=body.first_try, settings=settings
    )
