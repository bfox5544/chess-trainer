"""Read access to a user's puzzles."""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from chess_trainer.db.enums import Classification, Phase, PuzzleOutcome, PuzzleStatus
from chess_trainer.db.models import Puzzle


@dataclass(frozen=True)
class PuzzleFilters:
    outcome: PuzzleOutcome | None = None
    phase: Phase | None = None
    severity: Classification | None = None
    account_id: int | None = None


def list_puzzles(
    session: Session, user_id: int, filters: PuzzleFilters, limit: int = 20, offset: int = 0
) -> list[Puzzle]:
    """Accepted puzzles for a user, newest first."""
    conditions = [Puzzle.user_id == user_id, Puzzle.status == PuzzleStatus.ACCEPTED]
    if filters.outcome is not None:
        conditions.append(Puzzle.outcome == filters.outcome)
    if filters.phase is not None:
        conditions.append(Puzzle.phase == filters.phase)
    if filters.severity is not None:
        conditions.append(Puzzle.severity == filters.severity)
    if filters.account_id is not None:
        conditions.append(Puzzle.account_id == filters.account_id)
    stmt = select(Puzzle).where(*conditions).order_by(Puzzle.id.desc()).limit(limit).offset(offset)
    return list(session.scalars(stmt))


def motif_counts(session: Session, user_id: int, account_id: int | None = None) -> dict[str, int]:
    """How often each tactical motif appears in the user's accepted puzzles."""
    counts: dict[str, int] = {}
    for puzzle in list_puzzles(
        session, user_id, PuzzleFilters(account_id=account_id), limit=10_000
    ):
        for theme in puzzle.themes:
            counts[theme] = counts.get(theme, 0) + 1
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))
