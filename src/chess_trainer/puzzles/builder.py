"""Turn one mistake into a puzzle, or explain why it doesn't make a good one.

Pure: positions in, a draft out. Evaluations come through a callable so tests
can script them.

A mistake only becomes a puzzle when the position has **one clearly best
move** that leaves the solver at least equal. The line is then extended while
each further solver move is also the only good one. This "uniqueness" test is
a proxy for "tactical": it removes positions with several good moves and most
vague positional slips, but it cannot tell a quiet only-move from a
combination. That distinction is motif detection, a later phase.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum

import chess

from chess_trainer.analysis.cache import is_history_sensitive
from chess_trainer.analysis.engine import EvalLine, PositionEvaluation
from chess_trainer.analysis.winprob import win_pct
from chess_trainer.db.enums import PuzzleOutcome
from chess_trainer.puzzles.validators import first_rejection

# Bump when the rules below change, so stored puzzles can be told apart.
GENERATOR_VERSION = 1

# (board, number of lines wanted) -> evaluation
Evaluate = Callable[[chess.Board, int], PositionEvaluation]


@dataclass(frozen=True)
class PuzzleConfig:
    uniqueness_gap: float = 15.0  # win-% points the best move must beat the second by
    min_result_win_pct: float = 50.0  # solver must end up at least this well off
    max_plies: int = 10  # cap on the solution length (both sides' moves)
    crushing_win_pct: float = 85.0
    advantage_win_pct: float = 65.0


class RejectReason(StrEnum):
    HISTORY_SENSITIVE = "history_sensitive"  # eval depends on repetition / 50-move rule
    PLAYED_BEST = "played_best"  # deeper look says the played move was best after all
    NOT_UNIQUE = "not_unique"  # more than one good move
    STILL_LOST = "still_lost"  # even the best move leaves the solver worse


@dataclass(frozen=True)
class SolutionStep:
    uci: str
    san: str
    by: str  # "user" or "opponent"
    cp: int | None  # eval after this move with best play, White's point of view
    mate: int | None
    win_pct: float  # the solver's winning chances after this move
    # For user steps: the runner-up move, kept so uniqueness can be re-checked.
    second_best_uci: str | None = None
    second_best_win_pct: float | None = None


@dataclass(frozen=True)
class PuzzleDraft:
    reject_reason: str | None = None
    solution: list[SolutionStep] = field(default_factory=list)
    outcome: PuzzleOutcome | None = None
    uniqueness_gap: float | None = None

    @property
    def accepted(self) -> bool:
        return self.reject_reason is None

    @property
    def moves(self) -> list[chess.Move]:
        return [chess.Move.from_uci(step.uci) for step in self.solution]


@dataclass(frozen=True)
class Choice:
    """The solver's options in one position."""

    best: EvalLine
    best_win_pct: float
    second: EvalLine | None
    second_win_pct: float | None
    unique: bool

    @property
    def gap(self) -> float | None:
        return None if self.second_win_pct is None else self.best_win_pct - self.second_win_pct


def assess(board: chess.Board, evaluate: Evaluate, config: PuzzleConfig) -> Choice:
    """Compare the two best moves for the side to move."""
    solver = board.turn
    lines = evaluate(board, 2).lines
    best, second = lines[0], (lines[1] if len(lines) > 1 else None)
    best_pct = win_pct(best.eval, solver)
    second_pct = win_pct(second.eval, solver) if second else None
    return Choice(best, best_pct, second, second_pct, is_unique(best, second, solver, config))


def is_unique(
    best: EvalLine, second: EvalLine | None, solver: chess.Color, config: PuzzleConfig
) -> bool:
    if second is None:  # only one legal move
        return True
    if best.eval.is_mate_for(solver) and not second.eval.is_mate_for(solver):
        return True  # the only mating move is a solution even if others also win
    gap = win_pct(best.eval, solver) - win_pct(second.eval, solver)
    return gap >= config.uniqueness_gap


def user_step(board: chess.Board, choice: Choice) -> SolutionStep:
    move = chess.Move.from_uci(choice.best.pv[0])
    return SolutionStep(
        uci=move.uci(),
        san=board.san(move),
        by="user",
        cp=choice.best.eval.cp,
        mate=choice.best.eval.mate,
        win_pct=round(choice.best_win_pct, 1),
        second_best_uci=choice.second.pv[0] if choice.second else None,
        second_best_win_pct=(
            round(choice.second_win_pct, 1) if choice.second_win_pct is not None else None
        ),
    )


def opponent_step(board: chess.Board, reply: EvalLine, solver: chess.Color) -> SolutionStep:
    move = chess.Move.from_uci(reply.pv[0])
    return SolutionStep(
        uci=move.uci(),
        san=board.san(move),
        by="opponent",
        cp=reply.eval.cp,
        mate=reply.eval.mate,
        win_pct=round(win_pct(reply.eval, solver), 1),
    )


def extend_line(
    board: chess.Board, first: Choice, evaluate: Evaluate, config: PuzzleConfig
) -> list[SolutionStep]:
    """Follow the solution while the solver's next move stays unique.

    Each round adds the opponent's best reply plus the solver's answer, so the
    line always ends on a solver move. Stops at mate, at `max_plies`, or as
    soon as the solver would have a real choice.
    """
    solver = board.turn
    position = board.copy()
    steps = [user_step(position, first)]
    position.push(chess.Move.from_uci(first.best.pv[0]))
    while len(steps) + 2 <= config.max_plies and not position.is_game_over():
        reply = evaluate(position, 1).best
        reply_step = opponent_step(position, reply, solver)
        position.push(chess.Move.from_uci(reply.pv[0]))
        if position.is_game_over():
            break
        choice = assess(position, evaluate, config)
        if not choice.unique:
            break
        steps += [reply_step, user_step(position, choice)]
        position.push(chess.Move.from_uci(choice.best.pv[0]))
    return steps


def outcome_of(step: SolutionStep, config: PuzzleConfig) -> PuzzleOutcome:
    """What the solver has achieved after the final move of the solution."""
    if step.win_pct >= 100.0:
        return PuzzleOutcome.MATE
    if step.win_pct >= config.crushing_win_pct:
        return PuzzleOutcome.CRUSHING
    if step.win_pct >= config.advantage_win_pct:
        return PuzzleOutcome.ADVANTAGE
    return PuzzleOutcome.EQUALIZE


def build_puzzle(
    board: chess.Board, played: chess.Move, evaluate: Evaluate, config: PuzzleConfig
) -> PuzzleDraft:
    """`board` is the position before the user's mistake; `played` is the mistake."""
    if is_history_sensitive(board):
        return PuzzleDraft(RejectReason.HISTORY_SENSITIVE)
    first = assess(board, evaluate, config)
    if first.best.pv[0] == played.uci():
        return PuzzleDraft(RejectReason.PLAYED_BEST, uniqueness_gap=first.gap)
    if not first.unique:
        return PuzzleDraft(RejectReason.NOT_UNIQUE, uniqueness_gap=first.gap)
    if first.best_win_pct < config.min_result_win_pct:
        return PuzzleDraft(RejectReason.STILL_LOST, uniqueness_gap=first.gap)
    steps = extend_line(board, first, evaluate, config)
    draft = PuzzleDraft(None, steps, outcome_of(steps[-1], config), first.gap)
    invalid = first_rejection(board, draft.moves)
    return draft if invalid is None else PuzzleDraft(invalid, steps, None, first.gap)
