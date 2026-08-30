"""Engine access behind a small Protocol, so tests can use a fake."""

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from types import TracebackType
from typing import Protocol, Self

import chess
import chess.engine

from chess_trainer.analysis.winprob import Eval


@dataclass(frozen=True)
class EvalLine:
    eval: Eval  # White's point of view
    pv: tuple[str, ...]  # principal variation as UCI moves; pv[0] is the move itself


@dataclass(frozen=True)
class PositionEvaluation:
    depth: int
    lines: tuple[EvalLine, ...]  # best first; more than one when multipv > 1

    @property
    def best(self) -> EvalLine:
        return self.lines[0]


class Engine(Protocol):
    name: str  # includes the version, e.g. "Stockfish 17"
    # Options that change *what* the engine evaluates. Part of the cache
    # fingerprint. Speed-only options (Threads, Hash) must not go here.
    eval_options: Mapping[str, str]

    def analyse(self, board: chess.Board, depth: int, multipv: int) -> PositionEvaluation: ...


def fingerprint(engine_name: str, eval_options: Mapping[str, str]) -> str:
    """Stable identity for 'evaluations comparable with each other'."""
    payload = json.dumps({"name": engine_name, "options": dict(eval_options)}, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()


class StockfishEngine:
    """One long-lived UCI engine process."""

    def __init__(
        self, path: str, threads: int = 1, hash_mb: int = 64, eval_file: str | None = None
    ) -> None:
        self._engine = chess.engine.SimpleEngine.popen_uci(path)
        self.name: str = self._engine.id.get("name", "unknown engine")
        self.eval_options: Mapping[str, str] = {"EvalFile": eval_file} if eval_file else {}
        self._engine.configure({"Threads": threads, "Hash": hash_mb, **self.eval_options})

    def analyse(self, board: chess.Board, depth: int, multipv: int) -> PositionEvaluation:
        infos = self._engine.analyse(board, chess.engine.Limit(depth=depth), multipv=multipv)
        lines = tuple(to_line(info) for info in infos if "score" in info and info.get("pv"))
        if not lines:
            raise RuntimeError(f"engine returned no lines for {board.fen()}")
        # The engine may stop before `depth` once a result is proven (forced
        # mate). The answer still satisfies a depth-`depth` request, so record
        # at least that; otherwise the cache would never count it as a hit.
        reached = max(depth, min(info.get("depth", depth) for info in infos))
        return PositionEvaluation(reached, lines)

    def close(self) -> None:
        self._engine.quit()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()


def to_line(info: chess.engine.InfoDict) -> EvalLine:
    score = info["score"].white()
    mate = score.mate()
    evaluation = Eval(mate=mate) if mate is not None else Eval(cp=score.score())
    return EvalLine(evaluation, tuple(move.uci() for move in info["pv"]))
