"""Per-game report: every analyzed move plus a summary for each side."""

from collections.abc import Sequence
from dataclasses import dataclass, field

import chess
from sqlalchemy import select
from sqlalchemy.orm import Session

from chess_trainer.analysis.explain import MoveFacts, Reason, explain_move
from chess_trainer.analysis.highlights import highlight_text
from chess_trainer.analysis.winprob import Eval
from chess_trainer.db.enums import Color
from chess_trainer.db.models import AccountGame, Game, MoveAnalysis
from chess_trainer.reports.key_moments import KeyMoment, KeyMomentConfig, find_key_moments
from chess_trainer.reports.stats import MoveStats, summarize


@dataclass(frozen=True)
class GameReport:
    game: Game
    moves: list[MoveAnalysis]  # empty until the game has been analyzed
    white: MoveStats
    black: MoveStats
    # Parallel to `moves`: why each move was good or bad.
    explanations: list[list[Reason]] = field(default_factory=list)
    # The turning points among the tracked accounts' moves, in game order.
    key_moments: list[KeyMoment] = field(default_factory=list)


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
    reasons = explain_move(
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
    return [*highlight_reasons(move), *reasons]


def highlight_reasons(move: MoveAnalysis) -> list[Reason]:
    """Why a great or brilliant move earned its mark, listed first."""
    if move.highlight is None:
        return []
    text = highlight_text(
        move.highlight,
        chess.Board(move.fen_before),
        chess.Move.from_uci(move.uci),
        move.second_best_san,
        move.second_best_win_pct,
        move.win_pct_after,
    )
    return [Reason(move.highlight.value, text)]


def game_moves(session: Session, game_id: int) -> list[MoveAnalysis]:
    stmt = select(MoveAnalysis).where(MoveAnalysis.game_id == game_id).order_by(MoveAnalysis.ply)
    return list(session.scalars(stmt))


def tracked_colors(session: Session, game_id: int) -> set[Color]:
    """The colors a linked account played in this game."""
    stmt = select(AccountGame.color).where(AccountGame.game_id == game_id)
    return set(session.scalars(stmt))


def build_game_report(
    session: Session, game_id: int, moment_config: KeyMomentConfig | None = None
) -> GameReport | None:
    """None if the game does not exist."""
    game = session.get(Game, game_id)
    if game is None:
        return None
    moves = game_moves(session, game_id)
    explanations = [explain_at(moves, index) for index in range(len(moves))]
    moments = find_key_moments(
        moves, explanations, tracked_colors(session, game_id), moment_config or KeyMomentConfig()
    )
    return GameReport(
        game,
        moves,
        side_stats(moves, Color.WHITE),
        side_stats(moves, Color.BLACK),
        explanations,
        moments,
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


def move_at(session: Session, game_id: int, ply: int) -> MoveAnalysis | None:
    """The analyzed move at `ply` of a game, if there is one."""
    stmt = select(MoveAnalysis).where(MoveAnalysis.game_id == game_id, MoveAnalysis.ply == ply)
    return session.scalars(stmt).first()
