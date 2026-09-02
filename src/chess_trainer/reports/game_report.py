"""Per-game report: every analyzed move plus a summary for each side."""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from chess_trainer.db.enums import Color
from chess_trainer.db.models import Game, MoveAnalysis
from chess_trainer.reports.stats import MoveStats, summarize


@dataclass(frozen=True)
class GameReport:
    game: Game
    moves: list[MoveAnalysis]  # empty until the game has been analyzed
    white: MoveStats
    black: MoveStats


def side_stats(moves: list[MoveAnalysis], color: Color) -> MoveStats:
    return summarize((m.classification, m.win_pct_loss) for m in moves if m.color is color)


def build_game_report(session: Session, game_id: int) -> GameReport | None:
    """None if the game does not exist."""
    game = session.get(Game, game_id)
    if game is None:
        return None
    stmt = select(MoveAnalysis).where(MoveAnalysis.game_id == game_id).order_by(MoveAnalysis.ply)
    moves = list(session.scalars(stmt))
    return GameReport(game, moves, side_stats(moves, Color.WHITE), side_stats(moves, Color.BLACK))
