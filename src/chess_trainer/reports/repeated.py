"""Mistakes the user makes more than once: the same position, gone wrong in
several games.

Errors are grouped by the position they were made in (FEN without the move
counters), so the same mistake is found even when the games reached it by
different move orders or carry different opening names. A position counts
once per game, so shuffling pieces back and forth in one game never looks
like a habit.
"""

from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from chess_trainer.analysis.explain import Reason
from chess_trainer.db.enums import Classification, Color
from chess_trainer.db.models import Game, MoveAnalysis
from chess_trainer.reports.game_report import explain_ply
from chess_trainer.reports.weakness import UNKNOWN_OPENING, WeaknessFilters, user_moves_query

ERRORS = (Classification.INACCURACY, Classification.MISTAKE, Classification.BLUNDER)
SEVERITY = {kind: rank for rank, kind in enumerate(ERRORS)}
# Positions this deep rarely repeat; a longer path is shown as just a move number.
MAX_PATH_PLIES = 24


@dataclass(frozen=True)
class ErrorRow:
    """One of the user's errors, as loaded from the database."""

    game_id: int
    played_at: datetime | None
    opening_family: str | None
    ply: int
    move_number: int
    color: Color
    fen_before: str
    uci: str
    san: str
    best_move_uci: str | None
    best_move_san: str | None
    best_line: list[str]
    classification: Classification
    win_pct_loss: float


@dataclass(frozen=True)
class PlayedMove:
    san: str
    uci: str
    count: int  # games in which this move was played here


@dataclass
class RepeatedMistake:
    key: str  # the position, FEN without move counters
    fen: str
    color: Color
    move_number: int
    ply: int
    best_move_san: str | None
    best_move_uci: str | None
    best_line: list[str]  # the engine's line from here (UCI), starting with the best move
    worst: Classification
    average_win_pct_loss: float
    played: list[PlayedMove]  # most common first
    occurrences: list[ErrorRow]  # one per game, newest first
    families: list[str]  # opening families of those games, most common first
    path: list[str] = field(default_factory=list)  # SAN moves that lead here, if short
    explanation: list[Reason] = field(default_factory=list)

    @property
    def games(self) -> int:
        return len(self.occurrences)


def position_key(fen: str) -> str:
    return " ".join(fen.split()[:4])


def most_common(values: Iterable[str | None]) -> str | None:
    counts = Counter(value for value in values if value)
    return counts.most_common(1)[0][0] if counts else None


def group_errors(rows: Iterable[ErrorRow], min_games: int = 2) -> list[RepeatedMistake]:
    """Positions where the user erred in at least `min_games` games.

    Ordered by how many games repeat it, then how costly it was.
    """
    by_position: dict[str, dict[int, ErrorRow]] = defaultdict(dict)
    for row in sorted(rows, key=lambda r: (r.game_id, r.ply)):
        # setdefault keeps a game's first visit to the position
        by_position[position_key(row.fen_before)].setdefault(row.game_id, row)

    groups = []
    for key, per_game in by_position.items():
        if len(per_game) < min_games:
            continue
        rows_ = sorted(
            per_game.values(),
            key=lambda r: (r.played_at is not None, r.played_at or datetime.min, r.game_id),
            reverse=True,
        )
        moves = Counter((r.san, r.uci) for r in rows_)
        best_uci = most_common(r.best_move_uci for r in rows_)
        # the newest game whose engine line starts with that move supplies the line
        best = next((r for r in rows_ if r.best_move_uci == best_uci), None)
        families = Counter(r.opening_family or UNKNOWN_OPENING for r in rows_)
        first = rows_[0]
        groups.append(
            RepeatedMistake(
                key=key,
                fen=first.fen_before,
                color=first.color,
                move_number=first.move_number,
                ply=first.ply,
                best_move_san=best.best_move_san if best else None,
                best_move_uci=best_uci,
                best_line=list(best.best_line or []) if best else [],
                worst=max((r.classification for r in rows_), key=SEVERITY.__getitem__),
                average_win_pct_loss=round(sum(r.win_pct_loss for r in rows_) / len(rows_), 1),
                played=[PlayedMove(san, uci, n) for (san, uci), n in moves.most_common()],
                occurrences=rows_,
                families=[name for name, _ in families.most_common()],
            )
        )
    return sorted(groups, key=lambda g: (-g.games, -g.average_win_pct_loss, g.key))


def load_errors(session: Session, user_id: int, filters: WeaknessFilters) -> list[ErrorRow]:
    stmt = user_moves_query(user_id, filters).add_columns(
        Game.id,
        Game.played_at,
        Game.opening_family,
        MoveAnalysis.ply,
        MoveAnalysis.move_number,
        MoveAnalysis.color,
        MoveAnalysis.fen_before,
        MoveAnalysis.uci,
        MoveAnalysis.san,
        MoveAnalysis.best_move_uci,
        MoveAnalysis.best_move_san,
        MoveAnalysis.best_line,
        MoveAnalysis.classification,
        MoveAnalysis.win_pct_loss,
    )
    stmt = stmt.where(MoveAnalysis.classification.in_(ERRORS))
    return [ErrorRow(*row) for row in session.execute(stmt)]


def path_to(session: Session, game_id: int, ply: int) -> list[str]:
    if ply > MAX_PATH_PLIES:
        return []
    stmt = (
        select(MoveAnalysis.san)
        .where(MoveAnalysis.game_id == game_id, MoveAnalysis.ply < ply)
        .order_by(MoveAnalysis.ply)
    )
    return list(session.scalars(stmt))


def build_repeated_mistakes(
    session: Session,
    user_id: int,
    filters: WeaknessFilters,
    family: str | None = None,
    min_games: int = 2,
    limit: int = 20,
) -> list[RepeatedMistake]:
    """The user's repeated mistakes, optionally only in one opening family
    (counting only that family's games)."""
    rows = load_errors(session, user_id, filters)
    if family is not None:
        rows = [r for r in rows if (r.opening_family or UNKNOWN_OPENING) == family]
    groups = group_errors(rows, min_games)[:limit]
    for group in groups:
        latest = group.occurrences[0]
        group.path = path_to(session, latest.game_id, latest.ply)
        group.explanation = explain_ply(session, latest.game_id, latest.ply)
    return groups
