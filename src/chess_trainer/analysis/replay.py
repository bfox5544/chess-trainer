"""Replay a PGN into the positions and moves the analysis needs."""

import io
from dataclasses import dataclass

import chess
import chess.pgn


@dataclass(frozen=True)
class Ply:
    index: int  # 0-based: 0 is White's first move
    board_before: chess.Board  # keeps its move stack (needed for repetition checks)
    move: chess.Move
    san: str
    clock: float | None  # mover's remaining seconds after the move, if recorded


@dataclass(frozen=True)
class Replay:
    plies: list[Ply]
    final_board: chess.Board

    @property
    def boards(self) -> list[chess.Board]:
        """Every position of the game: N moves give N + 1 boards."""
        return [ply.board_before for ply in self.plies] + [self.final_board]


def replay_pgn(pgn: str) -> Replay:
    game = chess.pgn.read_game(io.StringIO(pgn))
    if game is None or game.errors:
        raise ValueError("PGN could not be parsed")
    board = game.board()
    plies: list[Ply] = []
    for index, node in enumerate(game.mainline()):
        before = board.copy()
        plies.append(Ply(index, before, node.move, before.san(node.move), node.clock()))
        board.push(node.move)
    if not plies:
        # python-chess reads arbitrary text as an empty game; that is not one
        # we can analyze, and silently storing zero moves would hide the problem.
        raise ValueError("PGN contains no moves")
    return Replay(plies, board)
