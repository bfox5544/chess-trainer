"""The user's great and brilliant moves across their analyzed games."""

from dataclasses import dataclass

from sqlalchemy import distinct, func, or_, select
from sqlalchemy.orm import Session

from chess_trainer.analysis.highlights import HIGHLIGHTS_VERSION
from chess_trainer.db.enums import Color, Highlight
from chess_trainer.db.models import AccountGame, ChessAccount, Game, MoveAnalysis
from chess_trainer.reports.game_report import highlight_reasons
from chess_trainer.reports.weakness import WeaknessFilters, user_moves_query


@dataclass(frozen=True)
class HighlightedMove:
    game: Game
    ply: int
    move_number: int
    color: Color
    san: str
    uci: str
    fen_before: str
    kind: Highlight
    win_pct_before: float
    win_pct_after: float
    second_best_san: str | None
    second_best_win_pct: float | None
    explanation: str


@dataclass(frozen=True)
class HighlightsReport:
    great: int
    brilliant: int
    # Analyzed games not yet checked (analyzed before the check existed);
    # the next analysis job checks them.
    unchecked_games: int
    moves: list[HighlightedMove]  # newest game first


def highlighted_move(move: MoveAnalysis, game: Game) -> HighlightedMove:
    assert move.highlight is not None
    (reason,) = highlight_reasons(move)
    return HighlightedMove(
        game=game,
        ply=move.ply,
        move_number=move.move_number,
        color=move.color,
        san=move.san,
        uci=move.uci,
        fen_before=move.fen_before,
        kind=move.highlight,
        win_pct_before=move.win_pct_before,
        win_pct_after=move.win_pct_after,
        second_best_san=move.second_best_san,
        second_best_win_pct=move.second_best_win_pct,
        explanation=reason.text,
    )


def count_by_kind(session: Session, user_id: int, filters: WeaknessFilters) -> dict[Highlight, int]:
    stmt = (
        user_moves_query(user_id, filters)
        .add_columns(MoveAnalysis.highlight, func.count())
        .where(MoveAnalysis.highlight.is_not(None))
        .group_by(MoveAnalysis.highlight)
    )
    return {kind: count for kind, count in session.execute(stmt)}


def unchecked_games(session: Session, user_id: int, filters: WeaknessFilters) -> int:
    conditions = [
        ChessAccount.user_id == user_id,
        Game.analyzed_depth.is_not(None),
        or_(Game.highlights_version.is_(None), Game.highlights_version < HIGHLIGHTS_VERSION),
    ]
    if filters.account_id is not None:
        conditions.append(ChessAccount.id == filters.account_id)
    if filters.time_class is not None:
        conditions.append(Game.time_class == filters.time_class)
    stmt = (
        select(func.count(distinct(Game.id)))
        .join(AccountGame, AccountGame.game_id == Game.id)
        .join(ChessAccount, ChessAccount.id == AccountGame.account_id)
        .where(*conditions)
    )
    return session.scalar(stmt) or 0


def build_highlights(
    session: Session,
    user_id: int,
    filters: WeaknessFilters,
    kind: Highlight | None = None,
    limit: int = 50,
    offset: int = 0,
) -> HighlightsReport:
    stmt = (
        user_moves_query(user_id, filters)
        .add_columns(MoveAnalysis, Game)
        .where(MoveAnalysis.highlight == kind if kind else MoveAnalysis.highlight.is_not(None))
        .order_by(Game.played_at.desc().nulls_last(), Game.id.desc(), MoveAnalysis.ply)
        .limit(limit)
        .offset(offset)
    )
    counts = count_by_kind(session, user_id, filters)
    return HighlightsReport(
        great=counts.get(Highlight.GREAT, 0),
        brilliant=counts.get(Highlight.BRILLIANT, 0),
        unchecked_games=unchecked_games(session, user_id, filters),
        moves=[highlighted_move(move, game) for move, game in session.execute(stmt)],
    )
