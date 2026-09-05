"""Turn a library puzzle into what the trainer plays. Pure.

A Lichess puzzle starts one move early: `moves[0]` is the opponent's move
that creates the tactic, shown to the solver before they move. Everything
after alternates solver, opponent, solver, ... and ends on a solver move.
"""

from collections.abc import Sequence
from dataclasses import dataclass

import chess

from chess_trainer.db.enums import Color


@dataclass(frozen=True)
class Step:
    uci: str
    san: str
    by: str  # "user" or "opponent"


@dataclass(frozen=True)
class TrainerLine:
    setup: Step  # the opponent's move played before the solver's turn
    start_fen: str  # position the solver faces
    user_color: Color
    solution: list[Step]


def trainer_line(fen: str, moves: Sequence[str]) -> TrainerLine:
    """Raises ValueError if the FEN or any move is illegal."""
    board = chess.Board(fen)
    played: list[Step] = []
    for index, uci in enumerate(moves):
        move = chess.Move.from_uci(uci)
        if move not in board.legal_moves:
            raise ValueError(f"illegal move {uci} at ply {index} of puzzle line")
        by = "opponent" if index % 2 == 0 else "user"
        played.append(Step(uci, board.san(move), by))
        board.push(move)
        if index == 0:
            start_fen = board.fen()
            user_color = Color.WHITE if board.turn == chess.WHITE else Color.BLACK
    if len(played) < 2:
        raise ValueError("a puzzle needs a setup move and at least one reply")
    return TrainerLine(played[0], start_fen, user_color, played[1:])
