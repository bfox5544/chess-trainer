"""Test doubles for the engine and the game sources."""

from collections.abc import Iterator

import chess

from chess_trainer.analysis.engine import EvalLine, PositionEvaluation
from chess_trainer.analysis.winprob import Eval
from chess_trainer.db.enums import Platform
from chess_trainer.ingestion.sources import FetchFilters, RawGame

ScriptedLines = list[tuple[str, Eval]]  # (uci move, eval from White's POV), best first


def position_after(*sans: str) -> chess.Board:
    board = chess.Board()
    for san in sans:
        board.push_san(san)
    return board


class FakeEngine:
    """Returns scripted evaluations and records every call.

    Unscripted positions evaluate as dead equal, with the alphabetically
    first legal moves as the candidate lines.
    """

    def __init__(self, script: dict[str, ScriptedLines] | None = None, name: str = "FakeFish 1"):
        self.name = name
        self.eval_options: dict[str, str] = {}
        self.script = script or {}
        self.calls: list[tuple[str, int, int]] = []  # (epd, depth, multipv)
        self.stacks: list[int] = []  # move-stack length of each analysed board

    def analyse(self, board: chess.Board, depth: int, multipv: int) -> PositionEvaluation:
        self.calls.append((board.epd(), depth, multipv))
        self.stacks.append(len(board.move_stack))
        lines = self.script.get(board.epd()) or self._default_lines(board)
        return PositionEvaluation(
            depth, tuple(EvalLine(evaluation, (uci,)) for uci, evaluation in lines[:multipv])
        )

    @staticmethod
    def _default_lines(board: chess.Board) -> ScriptedLines:
        return [(uci, Eval(cp=0)) for uci in sorted(m.uci() for m in board.legal_moves)]


class StubSource:
    """A GameSource that replays fixed games, so no HTTP is involved."""

    def __init__(self, games: list[RawGame], platform: Platform = Platform.LICHESS) -> None:
        self.platform = platform
        self._games = games

    def fetch_games(self, username: str, filters: FetchFilters) -> Iterator[RawGame]:
        yield from self._games[: filters.max_games]


def scholars_mate_script() -> dict[str, ScriptedLines]:
    """Evals for the Scholar's Mate fixture: 3...Nf6?? allows 4.Qxf7#.

    Before 3...Nf6 Black is fine and 3...g6 is the only good move (Qe7 is
    clearly worse); after it White has mate in one.
    """
    before_blunder = position_after("e4", "e5", "Bc4", "Nc6", "Qh5")
    after_blunder = position_after("e4", "e5", "Bc4", "Nc6", "Qh5", "Nf6")
    return {
        before_blunder.epd(): [("g7g6", Eval(cp=-30)), ("d8e7", Eval(cp=250))],
        after_blunder.epd(): [("h5f7", Eval(mate=1))],
    }
