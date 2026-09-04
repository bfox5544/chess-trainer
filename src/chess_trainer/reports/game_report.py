"""Per-game report: every analyzed move plus a summary for each side."""

from collections.abc import Sequence
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from chess_trainer.analysis.explain import MoveFacts, Reason, explain_move
from chess_trainer.analysis.winprob import Eval
from chess_trainer.db.enums import Color
from chess_trainer.db.models import Game, MoveAnalysis
from chess_trainer.reports.stats import MoveStats, summarize


@dataclass(frozen=True)
class GameReport:
    game: Game
    moves: list[MoveAnalysis]  # empty until the game has been analyzed
    white: MoveStats
    black: MoveStats
    # Parallel to `moves`: why each move was good or bad.
    explanations: list[list[Reason]] = field(default_factory=list)


def side_stats(moves: list[MoveAnalysis], color: Color) -> MoveStats:
    return summarize((m.classification, m.win_pct_loss) for m in moves if m.color is color)


def stored_eval(cp: int | None, mate: int | None) -> Eval:
    return Eval(cp=cp) if mate is None else Eval(mate=mate)


def explain_at(moves: Sequence[MoveAnalysis], index: int) -> list[Reason]:
    """Explain moves[index]. The opponent's punishing line is the next ply's
    best line, which the analysis already stored; consecutive plies are
    required so a gap in the data never pairs unrelated moves."""
    move = moves[index]
    following = moves[index + 1] if index + 1 < len(moves) else None
    previous = moves[index - 1] if index > 0 else None
    if following is not None and following.ply != move.ply + 1:
        following = None
    if previous is not None and previous.ply != move.ply - 1:
        previous = None
    return explain_move(
        MoveFacts(
            fen_before=move.fen_before,
            uci=move.uci,
            classification=move.classification,
            is_best=move.is_best,
            eval_before=stored_eval(move.eval_before_cp, move.eval_before_mate),
            eval_after=stored_eval(move.eval_after_cp, move.eval_after_mate),
            best_line=move.best_line,
            reply_line=following.best_line if following else [],
            previous_fen=previous.fen_before if previous else None,
            previous_uci=previous.uci if previous else None,
        )
    )


def game_moves(session: Session, game_id: int) -> list[MoveAnalysis]:
    stmt = select(MoveAnalysis).where(MoveAnalysis.game_id == game_id).order_by(MoveAnalysis.ply)
    return list(session.scalars(stmt))


def build_game_report(session: Session, game_id: int) -> GameReport | None:
    """None if the game does not exist."""
    game = session.get(Game, game_id)
    if game is None:
        return None
    moves = game_moves(session, game_id)
    explanations = [explain_at(moves, index) for index in range(len(moves))]
    return GameReport(
        game,
        moves,
        side_stats(moves, Color.WHITE),
        side_stats(moves, Color.BLACK),
        explanations,
    )


def explain_ply(session: Session, game_id: int, ply: int) -> list[Reason]:
    """Explanation for one move of a game (e.g. the mistake behind a puzzle)."""
    stmt = (
        select(MoveAnalysis)
        .where(MoveAnalysis.game_id == game_id, MoveAnalysis.ply.between(ply - 1, ply + 1))
        .order_by(MoveAnalysis.ply)
    )
    moves = list(session.scalars(stmt))
    for index, move in enumerate(moves):
        if move.ply == ply:
            return explain_at(moves, index)
    return []
