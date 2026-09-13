"""Puzzle rating, training profile and recommended puzzles against Postgres."""

import random
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from chess_trainer.config import Settings
from chess_trainer.db.enums import JobKind
from chess_trainer.db.models import ChessAccount, Game, LibraryAttempt, LibraryPuzzle
from chess_trainer.jobs import queue
from chess_trainer.jobs.handlers import JobContext
from chess_trainer.jobs.worker import work_once
from chess_trainer.library.parse import RowFilter
from chess_trainer.library.store import LibraryFilters, import_library, random_puzzles
from chess_trainer.training.focus import Group
from chess_trainer.training.mistakes import load_mistakes
from chess_trainer.training.service import (
    build_profile,
    rating_state,
    recommend,
    record_attempt,
)

FIXTURE = Path(__file__).parent.parent / "fixtures" / "library" / "lichess_db_puzzle.csv"


@pytest.fixture
def library(session: Session) -> list[LibraryPuzzle]:
    """The five accepted fixture puzzles, rated 1032 to 1819."""
    with FIXTURE.open() as lines:
        import_library(session, lines, limit=None, row_filter=RowFilter(50, 50), batch_size=10)
    return list(session.scalars(select(LibraryPuzzle).order_by(LibraryPuzzle.rating)))


@pytest.fixture
def analyzed_game(
    session: Session, bob: ChessAccount, scholars_game: Game, job_context: JobContext
) -> Game:
    """Bob's Scholar's Mate loss, analyzed. Bob is rated 1480 in it."""
    queue.enqueue(session, JobKind.ANALYZE, {"account_id": bob.id, "depth": 12})
    while work_once(session, job_context):
        pass
    return scholars_game


def test_rating_is_seeded_from_games_and_stored_on_the_first_attempt(
    session: Session,
    bob: ChessAccount,
    scholars_game: Game,
    library: list[LibraryPuzzle],
    settings: Settings,
) -> None:
    state = rating_state(session, bob.user_id, settings)
    assert state.seeded and state.rated_attempts == 0
    assert state.rating == scholars_game.black_rating  # Lichess game: no offset
    assert state.deviation == settings.puzzle_rating_initial_deviation

    puzzle = library[0]
    first = record_attempt(
        session, bob.user_id, puzzle, solved=True, first_try=True, settings=settings
    )
    assert first.rated and first.rating_after > first.rating_before == state.rating
    stored = rating_state(session, bob.user_id, settings)
    assert not stored.seeded and stored.rated_attempts == 1
    assert stored.deviation < state.deviation

    # A second go at the same puzzle is practice: stored, not rated.
    again = record_attempt(
        session, bob.user_id, puzzle, solved=True, first_try=True, settings=settings
    )
    assert not again.rated and again.rating_after == first.rating_after
    # Solving with a hint or a wrong move is a loss.
    other = record_attempt(
        session, bob.user_id, library[1], solved=True, first_try=False, settings=settings
    )
    assert other.rated and other.rating_after < other.rating_before
    attempts = session.scalars(select(LibraryAttempt).order_by(LibraryAttempt.id)).all()
    assert [(a.rated, a.first_try) for a in attempts] == [
        (True, True),
        (False, True),
        (True, False),
    ]


def test_user_without_rated_games_starts_at_the_default(
    session: Session, bob: ChessAccount, settings: Settings
) -> None:
    state = rating_state(session, bob.user_id, settings)
    assert (state.rating, state.seeded) == (settings.puzzle_rating_default, True)


def test_mistakes_are_tagged_from_stored_lines(
    session: Session, analyzed_game: Game, bob: ChessAccount
) -> None:
    (mistake,) = load_mistakes(session, bob.user_id, limit=50)
    assert mistake.game_id == analyzed_game.id
    assert mistake.motifs.allowed == {"mateIn1"}  # 3...Nf6 allows Qxf7#
    assert mistake.motifs.missed == frozenset()


def test_filters_by_opening_and_skip_attempted_puzzles(
    session: Session, bob: ChessAccount, library: list[LibraryPuzzle], settings: Settings
) -> None:
    french = random_puzzles(session, LibraryFilters(opening="French_Defense"), 10)
    assert [p.id for p in french] == ["0000H"]
    record_attempt(
        session, bob.user_id, french[0], solved=False, first_try=False, settings=settings
    )
    unseen = random_puzzles(session, LibraryFilters(unseen_by=bob.user_id), 10)
    assert len(unseen) == 4 and "0000H" not in {p.id for p in unseen}


def test_profile_and_recommendations(
    session: Session,
    bob: ChessAccount,
    analyzed_game: Game,
    library: list[LibraryPuzzle],
    settings: Settings,
) -> None:
    profile = build_profile(session, bob.user_id, settings)
    assert (profile.mistakes, profile.games, profile.library_size) == (1, 1, 5)
    # One game is no pattern, and the fixture library has no puzzle for its
    # opening or for the opening phase: only the level focus is left.
    assert [focus.group for focus in profile.foci] == [Group.LEVEL]

    found = recommend(session, bob.user_id, settings, count=3, rng=random.Random(2))
    assert len({r.puzzle.id for r in found}) == 3
    # Bob is rated 1480: the closest puzzles come first as the window widens.
    assert all(abs(r.puzzle.rating - 1480) <= 4 * settings.training_rating_window for r in found)

    # Attempted puzzles are never recommended again, and the well runs dry.
    for puzzle in library:
        record_attempt(session, bob.user_id, puzzle, solved=True, first_try=True, settings=settings)
    assert recommend(session, bob.user_id, settings, count=3) == []
    progress = build_profile(session, bob.user_id, settings).progress
    assert (progress.puzzles, progress.solved, progress.first_try) == (5, 5, 5)


def test_training_api(
    client: TestClient,
    session: Session,
    bob: ChessAccount,
    analyzed_game: Game,
    library: list[LibraryPuzzle],
) -> None:
    user = bob.user_id
    rating = client.get(f"/users/{user}/puzzle-rating").json()
    assert rating["seeded"] and rating["rating"] == 1480

    profile = client.get(f"/users/{user}/training").json()
    assert profile["rating"] == rating and profile["library_size"] == 5
    assert profile["foci"][-1]["group"] == "level"

    picks = client.get(f"/users/{user}/recommended-puzzles", params={"limit": 2}).json()
    assert len(picks) == 2 and all(pick["focus"]["reason"] for pick in picks)
    skipped = picks[0]["puzzle"]["id"]
    others = client.get(
        f"/users/{user}/recommended-puzzles", params={"limit": 30, "exclude": skipped}
    ).json()
    assert skipped not in {pick["puzzle"]["id"] for pick in others}

    body = {"puzzle_id": skipped, "solved": False, "first_try": False}
    result = client.post(f"/users/{user}/library-attempts", json=body).json()
    assert result["rated"] and result["rating_after"] < result["rating_before"] == 1480
    assert client.get(f"/users/{user}/puzzle-rating").json()["rated_attempts"] == 1
    missing = {"puzzle_id": "nope", "solved": True, "first_try": True}
    assert client.post(f"/users/{user}/library-attempts", json=missing).status_code == 404
    assert client.get("/users/999999/training").status_code == 404
