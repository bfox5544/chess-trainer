"""Build per-move analysis records from positions and their evaluations.

Pure: no database and no engine. The pipeline feeds it evaluations and stores
what it returns.
"""

from dataclasses import dataclass

import chess

from chess_trainer.analysis.classify import Thresholds, classify, win_pct_loss
from chess_trainer.analysis.clock import time_spent
from chess_trainer.analysis.engine import PositionEvaluation
from chess_trainer.analysis.replay import Ply
from chess_trainer.analysis.winprob import Eval, win_pct
from chess_trainer.db.enums import Classification, Color, Phase


@dataclass(frozen=True)
class MoveRecord:
    ply: int
    move_number: int
    color: Color
    san: str
    uci: str
    fen_before: str
    eval_before: Eval
    eval_after: Eval
    eval_depth_before: int
    eval_depth_after: int
    best_move_uci: str | None
    best_move_san: str | None
    best_line: list[str]
    win_pct_before: float
    win_pct_after: float
    win_pct_loss: float
    classification: Classification
    is_best: bool
    is_forced: bool
    in_book: bool
    phase: Phase
    clock_remaining_s: float | None
    time_spent_s: float | None


@dataclass(frozen=True)
class GameContext:
    """Per-game facts every move record needs."""

    thresholds: Thresholds
    opening_ply: int  # moves with ply < opening_ply are book moves
    base_seconds: int | None
    increment_seconds: int | None


def build_move_record(
    ply: Ply,
    before: PositionEvaluation,
    after: PositionEvaluation,
    phase: Phase,
    previous_clock: float | None,
    context: GameContext,
) -> MoveRecord:
    board = ply.board_before
    mover = board.turn
    best_uci = before.best.pv[0] if before.best.pv else None
    is_best = best_uci == ply.move.uci()
    is_forced = board.legal_moves.count() == 1
    loss = win_pct_loss(
        before.best.eval, after.best.eval, mover, played_best=is_best, forced=is_forced
    )
    return MoveRecord(
        ply=ply.index,
        move_number=board.fullmove_number,
        color=Color.WHITE if mover == chess.WHITE else Color.BLACK,
        san=ply.san,
        uci=ply.move.uci(),
        fen_before=board.fen(),
        eval_before=before.best.eval,
        eval_after=after.best.eval,
        eval_depth_before=before.depth,
        eval_depth_after=after.depth,
        best_move_uci=best_uci,
        best_move_san=board.san(chess.Move.from_uci(best_uci)) if best_uci else None,
        best_line=list(before.best.pv),
        win_pct_before=win_pct(before.best.eval, mover),
        win_pct_after=win_pct(after.best.eval, mover),
        win_pct_loss=loss,
        classification=classify(loss, context.thresholds),
        is_best=is_best,
        is_forced=is_forced,
        in_book=ply.index < context.opening_ply,
        phase=phase,
        clock_remaining_s=ply.clock,
        time_spent_s=time_spent(previous_clock, ply.clock, context.increment_seconds or 0),
    )


def build_move_records(
    plies: list[Ply],
    evaluations: list[PositionEvaluation],
    phases: list[Phase],
    context: GameContext,
) -> list[MoveRecord]:
    """`evaluations[i]` and `phases[i]` describe the position before `plies[i]`;
    `evaluations` has one extra entry for the final position."""
    records: list[MoveRecord] = []
    # Each side's previous clock; both start with the full base time.
    clocks: dict[chess.Color, float | None] = {
        chess.WHITE: context.base_seconds,
        chess.BLACK: context.base_seconds,
    }
    for ply in plies:
        mover = ply.board_before.turn
        records.append(
            build_move_record(
                ply,
                evaluations[ply.index],
                evaluations[ply.index + 1],
                phases[ply.index],
                clocks[mover],
                context,
            )
        )
        clocks[mover] = ply.clock
    return records
