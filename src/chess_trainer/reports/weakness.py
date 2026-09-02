"""Weakness report: where does this user lose winning chances?

Loads one lightweight row per move the user played and aggregates in Python.
That keeps the grouping logic pure and easy to test; a few hundred games is
tens of thousands of rows, well within what this handles instantly. If it ever
stops being true, `aggregate` can be replaced by SQL `GROUP BY` without
touching callers.
"""

from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from chess_trainer.analysis.clock import is_time_pressure
from chess_trainer.config import Settings
from chess_trainer.db.enums import Classification, Phase, TimeClass
from chess_trainer.db.models import AccountGame, ChessAccount, Game, MoveAnalysis
from chess_trainer.puzzles.service import motif_counts
from chess_trainer.reports.stats import MoveStats, summarize

UNKNOWN_OPENING = "Unknown"
UNDER_PRESSURE = "under_pressure"
NOT_UNDER_PRESSURE = "not_under_pressure"


@dataclass(frozen=True)
class WeaknessFilters:
    account_id: int | None = None  # None = all of the user's accounts
    time_class: TimeClass | None = None
    since: datetime | None = None


@dataclass(frozen=True)
class MoveFact:
    """The facts about one of the user's moves that the report groups by."""

    classification: Classification
    win_pct_loss: float
    phase: Phase
    opening_family: str | None
    time_pressure: bool | None  # None = no clock data for this move


@dataclass(frozen=True)
class Bucket:
    key: str
    stats: MoveStats


@dataclass(frozen=True)
class WeaknessReport:
    games_analyzed: int
    overall: MoveStats
    by_phase: list[Bucket]
    by_opening: list[Bucket]
    by_time_pressure: list[Bucket]
    # Motif -> number of the user's puzzles showing it. Empty until motif
    # taggers exist (reports/motifs.py).
    by_motif: dict[str, int]


def aggregate(facts: Iterable[MoveFact], key: Callable[[MoveFact], str | None]) -> list[Bucket]:
    """Group facts by `key` (facts whose key is None are left out).

    Buckets come back largest first, so the most reliable numbers lead.
    """
    groups: dict[str, list[MoveFact]] = defaultdict(list)
    for fact in facts:
        group = key(fact)
        if group is not None:
            groups[group].append(fact)
    buckets = [Bucket(name, stats_of(members)) for name, members in groups.items()]
    return sorted(buckets, key=lambda b: (-b.stats.moves, b.key))


def stats_of(facts: Iterable[MoveFact]) -> MoveStats:
    return summarize((f.classification, f.win_pct_loss) for f in facts)


def phase_key(fact: MoveFact) -> str:
    return fact.phase.value


def opening_key(fact: MoveFact) -> str:
    return fact.opening_family or UNKNOWN_OPENING


def time_pressure_key(fact: MoveFact) -> str | None:
    if fact.time_pressure is None:
        return None
    return UNDER_PRESSURE if fact.time_pressure else NOT_UNDER_PRESSURE


def by_phase(facts: list[MoveFact]) -> list[Bucket]:
    """Phases in game order rather than by size."""
    order = [phase.value for phase in Phase]
    return sorted(aggregate(facts, phase_key), key=lambda b: order.index(b.key))


def _user_moves(user_id: int, filters: WeaknessFilters):  # type: ignore[no-untyped-def]
    """FROM/WHERE shared by the queries: moves the user played, by color."""
    conditions = [ChessAccount.user_id == user_id, MoveAnalysis.is_forced.is_(False)]
    if filters.account_id is not None:
        conditions.append(ChessAccount.id == filters.account_id)
    if filters.time_class is not None:
        conditions.append(Game.time_class == filters.time_class)
    if filters.since is not None:
        conditions.append(Game.played_at >= filters.since)
    return (
        select()
        .select_from(MoveAnalysis)
        .join(Game, Game.id == MoveAnalysis.game_id)
        .join(
            AccountGame,
            (AccountGame.game_id == Game.id) & (AccountGame.color == MoveAnalysis.color),
        )
        .join(ChessAccount, ChessAccount.id == AccountGame.account_id)
        .where(*conditions)
    )


def load_move_facts(
    session: Session, user_id: int, filters: WeaknessFilters, settings: Settings
) -> list[MoveFact]:
    """The user's own, non-forced moves from analyzed games."""
    stmt = _user_moves(user_id, filters).add_columns(
        MoveAnalysis.classification,
        MoveAnalysis.win_pct_loss,
        MoveAnalysis.phase,
        Game.opening_family,
        MoveAnalysis.clock_remaining_s,
        Game.base_seconds,
    )
    return [
        MoveFact(
            classification,
            loss,
            phase,
            family,
            is_time_pressure(
                clock, base, settings.time_pressure_seconds, settings.time_pressure_fraction
            ),
        )
        for classification, loss, phase, family, clock, base in session.execute(stmt)
    ]


def count_games(session: Session, user_id: int, filters: WeaknessFilters) -> int:
    stmt = _user_moves(user_id, filters).add_columns(func.count(Game.id.distinct()))
    return session.execute(stmt).scalar_one()


def build_weakness_report(
    session: Session,
    user_id: int,
    filters: WeaknessFilters,
    settings: Settings,
    max_openings: int = 10,
) -> WeaknessReport:
    facts = load_move_facts(session, user_id, filters, settings)
    return WeaknessReport(
        games_analyzed=count_games(session, user_id, filters),
        overall=stats_of(facts),
        by_phase=by_phase(facts),
        by_opening=aggregate(facts, opening_key)[:max_openings],
        by_time_pressure=aggregate(facts, time_pressure_key),
        by_motif=motif_counts(session, user_id, filters.account_id),
    )
