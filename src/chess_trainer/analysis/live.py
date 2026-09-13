"""Score a single move outside a stored game, the way game analysis does.

Backs "keep playing" after a puzzle or from a repeated mistake: the player
tries a move in any position and gets the same classification, win-chance
loss and explanation a move in an analyzed game would get, plus the engine's
reply so play can go on.

Evaluations go through the shared cache, so positions already seen in the
player's games (or earlier in the same session) cost nothing.
"""

from dataclasses import dataclass

import chess

from chess_trainer.analysis.cache import Evaluator
from chess_trainer.analysis.classify import Thresholds, classify, win_pct_loss
from chess_trainer.analysis.explain import MoveFacts, Reason, explain_move
from chess_trainer.analysis.winprob import Eval, win_pct
from chess_trainer.db.enums import Classification, Color


@dataclass(frozen=True)
class EngineMove:
    uci: str
    san: str
    fen_after: str


@dataclass(frozen=True)
class MoveScore:
    uci: str
    san: str
    color: Color
    move_number: int
    fen_before: str
    fen_after: str
    classification: Classification
    is_best: bool
    is_forced: bool
    in_book: bool  # always False: there is no game to match an opening against
    win_pct_before: float  # the mover's winning chances
    win_pct_after: float
    win_pct_loss: float
    eval_after: Eval  # White's point of view
    best_move_uci: str | None
    best_move_san: str | None
    best_line: list[str]
    explanation: list[Reason]
    reply: EngineMove | None  # the engine's answer; None when the game is over


def parse_position(fen: str) -> chess.Board:
    """Raises ValueError for a FEN that is malformed or not a legal position."""
    board = chess.Board(fen)
    if not board.is_valid():
        raise ValueError("not a legal chess position")
    return board


def engine_move(board: chess.Board, uci: str) -> EngineMove:
    move = chess.Move.from_uci(uci)
    san = board.san(move)
    after = board.copy(stack=False)
    after.push(move)
    return EngineMove(uci, san, after.fen())


def best_move(evaluator: Evaluator, fen: str, depth: int) -> EngineMove | None:
    """The engine's move in this position; None if the game is over."""
    board = parse_position(fen)
    if board.is_game_over(claim_draw=False):
        return None
    pv = evaluator.evaluate(board, depth).best.pv
    return engine_move(board, pv[0]) if pv else None


def score_move(
    evaluator: Evaluator, fen: str, uci: str, depth: int, thresholds: Thresholds
) -> MoveScore:
    """Classify `uci` played in `fen`. Raises ValueError if the position or
    the move is not legal."""
    board = parse_position(fen)
    move = chess.Move.from_uci(uci)
    if move not in board.legal_moves:
        raise ValueError(f"{uci} is not a legal move in this position")
    mover = board.turn
    after_board = board.copy(stack=False)
    after_board.push(move)
    before, after = evaluator.evaluate_many([board, after_board], depth)

    best_uci = before.best.pv[0] if before.best.pv else None
    is_best = best_uci == uci
    is_forced = board.legal_moves.count() == 1
    loss = win_pct_loss(
        before.best.eval, after.best.eval, mover, played_best=is_best, forced=is_forced
    )
    classification = classify(loss, thresholds)
    reply_pv = list(after.best.pv)
    explanation = explain_move(
        MoveFacts(
            fen_before=fen,
            uci=uci,
            classification=classification,
            is_best=is_best,
            eval_before=before.best.eval,
            eval_after=after.best.eval,
            best_line=list(before.best.pv),
            reply_line=reply_pv,
        )
    )
    game_over = after_board.is_game_over(claim_draw=False)
    return MoveScore(
        uci=uci,
        san=board.san(move),
        color=Color.WHITE if mover == chess.WHITE else Color.BLACK,
        move_number=board.fullmove_number,
        fen_before=fen,
        fen_after=after_board.fen(),
        classification=classification,
        is_best=is_best,
        is_forced=is_forced,
        in_book=False,
        win_pct_before=win_pct(before.best.eval, mover),
        win_pct_after=win_pct(after.best.eval, mover),
        win_pct_loss=loss,
        eval_after=after.best.eval,
        best_move_uci=best_uci,
        best_move_san=board.san(chess.Move.from_uci(best_uci)) if best_uci else None,
        best_line=list(before.best.pv),
        explanation=explanation,
        reply=engine_move(after_board, reply_pv[0]) if reply_pv and not game_over else None,
    )
