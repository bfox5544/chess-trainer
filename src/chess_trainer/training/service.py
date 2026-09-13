"""Personal training on the Lichess puzzle library: the user's puzzle rating,
their training profile, recording attempts, and picking puzzles for them."""

import random
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from chess_trainer.config import Settings
from chess_trainer.db.base import utcnow
from chess_trainer.db.enums import Color, Phase, Platform, TimeClass
from chess_trainer.db.models import (
    AccountGame,
    ChessAccount,
    Game,
    LibraryAttempt,
    LibraryPuzzle,
    PuzzleRating,
)
from chess_trainer.library.store import LibraryFilters, library_size, random_puzzles
from chess_trainer.training.focus import (
    Focus,
    Group,
    MotifCount,
    Signals,
    allocate,
    build_foci,
)
from chess_trainer.training.mistakes import Mistake, load_mistakes
from chess_trainer.training.rating import Rating, seed_rating, update

# Recent rated games that seed a puzzle rating.
SEED_GAMES = 30
# The rating window is widened by these factors until a puzzle is found.
WINDOW_STEPS = (1, 2, 4)


@dataclass(frozen=True)
class RatingState:
    rating: float
    deviation: float
    rated_attempts: int
    seeded: bool  # still the starting estimate: no puzzle has been rated yet


@dataclass(frozen=True)
class AttemptResult:
    rated: bool  # false for a repeat attempt at the same puzzle
    rating_before: float
    rating_after: float
    deviation: float


@dataclass(frozen=True)
class Progress:
    puzzles: int  # distinct library puzzles attempted
    solved: int  # of those, solved at some point
    first_try: int  # of those, solved cleanly on the first attempt


@dataclass(frozen=True)
class TrainingProfile:
    rating: RatingState
    foci: list[Focus]
    mistakes: int  # mistakes and blunders the profile is drawn from
    games: int  # analyzed games those came from
    progress: Progress
    library_size: int


@dataclass(frozen=True)
class Recommendation:
    puzzle: LibraryPuzzle
    focus: Focus


# --- Rating --------------------------------------------------------------------


def game_ratings(session: Session, user_id: int, settings: Settings) -> list[float]:
    """The user's rating in their most recent rated games, moved onto the
    Lichess scale."""
    rating = case((AccountGame.color == Color.WHITE, Game.white_rating), else_=Game.black_rating)
    stmt = (
        select(rating, ChessAccount.platform)
        .select_from(AccountGame)
        .join(Game, Game.id == AccountGame.game_id)
        .join(ChessAccount, ChessAccount.id == AccountGame.account_id)
        .where(ChessAccount.user_id == user_id, rating.is_not(None))
        .order_by(Game.played_at.desc().nulls_last(), Game.id.desc())
        .limit(SEED_GAMES)
    )
    offsets = {Platform.CHESSCOM: settings.puzzle_rating_chesscom_offset}
    return [value + offsets.get(platform, 0.0) for value, platform in session.execute(stmt)]


def rating_state(session: Session, user_id: int, settings: Settings) -> RatingState:
    """The user's puzzle rating. Until a puzzle has been rated it is an
    estimate from their games and nothing is stored."""
    stored = session.get(PuzzleRating, user_id)
    if stored is not None:
        return RatingState(stored.rating, stored.deviation, stored.rated_attempts, seeded=False)
    seed = seed_rating(game_ratings(session, user_id, settings), settings.puzzle_rating_default)
    return RatingState(seed, settings.puzzle_rating_initial_deviation, 0, seeded=True)


def record_attempt(
    session: Session,
    user_id: int,
    puzzle: LibraryPuzzle,
    *,
    solved: bool,
    first_try: bool,
    settings: Settings,
) -> AttemptResult:
    """Store a finished attempt. The user's first attempt at a puzzle is
    rated: a clean solve is a win, anything else (a wrong move, a hint, the
    solution shown) a loss. Repeats are stored but leave the rating alone."""
    stored = session.get(PuzzleRating, user_id, with_for_update=True)
    if stored is None:
        state = rating_state(session, user_id, settings)
        stored = PuzzleRating(
            user_id=user_id, rating=state.rating, deviation=state.deviation, rated_attempts=0
        )
        session.add(stored)
    repeat = session.scalar(
        select(LibraryAttempt.id)
        .where(LibraryAttempt.user_id == user_id, LibraryAttempt.puzzle_id == puzzle.id)
        .limit(1)
    )
    before = stored.rating
    rated = repeat is None
    if rated:
        after = update(
            Rating(stored.rating, stored.deviation),
            puzzle.rating,
            puzzle.rating_deviation,
            solved and first_try,
            settings.puzzle_rating_min_deviation,
        )
        stored.rating, stored.deviation = after.rating, after.deviation
        stored.rated_attempts += 1
        stored.updated_at = utcnow()
    session.add(
        LibraryAttempt(
            user_id=user_id,
            puzzle_id=puzzle.id,
            solved=solved,
            first_try=solved and first_try,
            rated=rated,
            puzzle_rating=puzzle.rating,
            rating_before=before if rated else None,
            rating_after=stored.rating if rated else None,
        )
    )
    session.flush()
    return AttemptResult(rated, before, stored.rating, stored.deviation)


def progress(session: Session, user_id: int) -> Progress:
    per_puzzle = (
        select(
            func.bool_or(LibraryAttempt.solved).label("solved"),
            func.bool_or(LibraryAttempt.rated & LibraryAttempt.first_try).label("first_try"),
        )
        .where(LibraryAttempt.user_id == user_id)
        .group_by(LibraryAttempt.puzzle_id)
        .subquery()
    )
    row = session.execute(
        select(
            func.count(),
            func.count().filter(per_puzzle.c.solved),
            func.count().filter(per_puzzle.c.first_try),
        ).select_from(per_puzzle)
    ).one()
    return Progress(*row)


# --- Profile -------------------------------------------------------------------


def motif_counts(mistakes: Iterable[Mistake]) -> list[MotifCount]:
    """Games in which each motif was missed or allowed."""
    missed: dict[str, set[int]] = defaultdict(set)
    allowed: dict[str, set[int]] = defaultdict(set)
    for mistake in mistakes:
        for theme in mistake.motifs.missed:
            missed[theme].add(mistake.game_id)
        for theme in mistake.motifs.allowed:
            allowed[theme].add(mistake.game_id)
    return [
        MotifCount(theme, len(missed[theme]), len(allowed[theme]))
        for theme in sorted(missed.keys() | allowed.keys())
    ]


def phase_errors(mistakes: Iterable[Mistake]) -> dict[Phase, int]:
    counts: dict[Phase, int] = defaultdict(int)
    for mistake in mistakes:
        counts[mistake.phase] += 1
    return dict(counts)


def games_played(
    session: Session, user_id: int
) -> tuple[list[tuple[str, int]], dict[TimeClass, int]]:
    """How many games the user played in each opening family and at each
    time control."""
    stmt = (
        select(Game.opening_family, Game.time_class, func.count())
        .select_from(AccountGame)
        .join(Game, Game.id == AccountGame.game_id)
        .join(ChessAccount, ChessAccount.id == AccountGame.account_id)
        .where(ChessAccount.user_id == user_id)
        .group_by(Game.opening_family, Game.time_class)
    )
    openings: dict[str, int] = defaultdict(int)
    time_classes: dict[TimeClass, int] = defaultdict(int)
    for family, time_class, count in session.execute(stmt):
        if family:
            openings[family] += count
        if time_class:
            time_classes[time_class] += count
    return list(openings.items()), dict(time_classes)


def load_signals(session: Session, user_id: int, settings: Settings) -> tuple[Signals, int, int]:
    """The user's signals, and how many mistakes and games they come from."""
    mistakes = load_mistakes(session, user_id, settings.training_mistake_sample)
    openings, time_classes = games_played(session, user_id)
    signals = Signals(motif_counts(mistakes), phase_errors(mistakes), openings, time_classes)
    return signals, len(mistakes), len({m.game_id for m in mistakes})


def has_puzzles(session: Session, focus: Focus) -> bool:
    filters = LibraryFilters(theme=focus.theme, opening=focus.opening)
    return bool(random_puzzles(session, filters, 1))


def build_profile(session: Session, user_id: int, settings: Settings) -> TrainingProfile:
    """What the user should train. A focus the loaded library has no puzzles
    for is left out (the level focus always stays)."""
    signals, mistakes, games = load_signals(session, user_id, settings)
    foci = [
        focus
        for focus in build_foci(signals)
        if focus.group is Group.LEVEL or has_puzzles(session, focus)
    ]
    return TrainingProfile(
        rating=rating_state(session, user_id, settings),
        foci=foci,
        mistakes=mistakes,
        games=games,
        progress=progress(session, user_id),
        library_size=library_size(session),
    )


# --- Recommendations -----------------------------------------------------------


def pick(
    session: Session,
    focus: Focus,
    rating: float,
    window: int,
    user_id: int,
    exclude: Sequence[str],
    rng: random.Random,
) -> LibraryPuzzle | None:
    """A puzzle for this focus the user has not attempted, rated as close to
    them as the library allows."""
    for step in WINDOW_STEPS:
        filters = LibraryFilters(
            rating_min=round(rating) - window * step,
            rating_max=round(rating) + window * step,
            theme=focus.theme,
            opening=focus.opening,
            unseen_by=user_id,
        )
        found = random_puzzles(session, filters, 1, exclude, rng.random)
        if found:
            return found[0]
    return None


def recommend(
    session: Session,
    user_id: int,
    settings: Settings,
    count: int,
    exclude: Sequence[str] = (),
    rng: random.Random | None = None,
) -> list[Recommendation]:
    """Up to `count` puzzles for the user, each with the focus it trains.
    When a focus has no unseen puzzle near the user's rating, the slot goes
    to a puzzle at their level instead, and says so."""
    rng = rng or random.Random()
    profile = build_profile(session, user_id, settings)
    level = next(focus for focus in profile.foci if focus.group is Group.LEVEL)
    anything = Focus(Group.LEVEL, "any", "Puzzles at your level", level.reason, 1.0)
    taken = list(exclude)
    found: list[Recommendation] = []
    for focus in allocate(profile.foci, count, rng):
        for candidate in dict.fromkeys((focus, level, anything)):
            puzzle = pick(
                session,
                candidate,
                profile.rating.rating,
                settings.training_rating_window,
                user_id,
                taken,
                rng,
            )
            if puzzle is not None:
                found.append(Recommendation(puzzle, candidate))
                taken.append(puzzle.id)
                break
    return found
