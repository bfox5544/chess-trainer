"""Position-evaluation cache and the Evaluator that uses it.

Rules (see README "Evaluation cache"):
- A cached row answers a request only if it was produced by a compatible
  engine config, at >= the requested depth, with >= the requested line count.
- A row is only ever overwritten by a deeper search.
- Positions whose evaluation depends on the game's history are never cached.
"""

from collections.abc import Iterable, Sequence

import chess
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from chess_trainer.analysis.engine import Engine, EvalLine, PositionEvaluation, fingerprint
from chess_trainer.analysis.winprob import Eval
from chess_trainer.db.base import utcnow
from chess_trainer.db.models import EngineConfig, PositionEval

# The 50-move rule draws at halfmove clock 100; from here on it starts to
# bend evaluations toward 0.00.
HALFMOVE_CLOCK_SENSITIVE_FROM = 80


def position_key(board: chess.Board) -> str:
    """Pieces, side to move, castling rights, en-passant square (if capturable).

    Leaves out the move counters so the same position reached by different
    move orders, or in different games, shares one cache row.
    """
    return board.epd()


def is_history_sensitive(board: chess.Board) -> bool:
    """True when the evaluation depends on more than the position itself.

    A repeated position may be evaluated as a draw by repetition, and a high
    halfmove clock pulls the score toward a 50-move draw. Neither fact is in
    the cache key, so such positions are analyzed with their move history and
    kept out of the cache.
    """
    return board.halfmove_clock >= HALFMOVE_CLOCK_SENSITIVE_FROM or board.is_repetition(2)


def terminal_evaluation(board: chess.Board, depth: int) -> PositionEvaluation | None:
    """Score finished games from the rules; engines have nothing to search."""
    outcome = board.outcome(claim_draw=False)
    if outcome is None:
        return None
    evaluation = Eval.draw() if outcome.winner is None else Eval.checkmate(outcome.winner)
    return PositionEvaluation(depth, (EvalLine(evaluation, ()),))


def get_or_create_engine_config(session: Session, engine: Engine) -> EngineConfig:
    digest = fingerprint(engine.name, engine.eval_options)
    stmt = (
        insert(EngineConfig)
        .values(engine_name=engine.name, options=dict(engine.eval_options), fingerprint=digest)
        .on_conflict_do_nothing(index_elements=["fingerprint"])
    )
    session.execute(stmt)
    return session.scalars(select(EngineConfig).where(EngineConfig.fingerprint == digest)).one()


def lines_to_json(lines: Iterable[EvalLine]) -> list[dict[str, object]]:
    return [{"cp": ln.eval.cp, "mate": ln.eval.mate, "pv": list(ln.pv)} for ln in lines]


def lines_from_json(raw: Iterable[dict[str, object]]) -> tuple[EvalLine, ...]:
    return tuple(
        EvalLine(Eval(cp=item["cp"], mate=item["mate"]), tuple(item["pv"]))  # type: ignore[arg-type]
        for item in raw
    )


class EvalCache:
    def __init__(self, session: Session, engine_config_id: int) -> None:
        self._session = session
        self._config_id = engine_config_id

    def get_many(
        self, keys: Iterable[str], depth: int, multipv: int
    ) -> dict[str, PositionEvaluation]:
        """Usable cached evaluations, deepest first when several rows qualify."""
        stmt = (
            select(PositionEval)
            .where(
                PositionEval.position_key.in_(set(keys)),
                PositionEval.engine_config_id == self._config_id,
                PositionEval.depth >= depth,
                PositionEval.multipv >= multipv,
            )
            .order_by(PositionEval.depth)
        )
        found: dict[str, PositionEvaluation] = {}
        for row in self._session.scalars(stmt):  # later (deeper) rows overwrite
            lines = lines_from_json(row.lines)[:multipv]
            found[row.position_key] = PositionEvaluation(row.depth, lines)
        return found

    def put(self, key: str, evaluation: PositionEvaluation, multipv: int) -> None:
        """Store unless an equally deep or deeper row already exists.

        The `WHERE` on the upsert makes "deeper wins" atomic, so concurrent
        workers cannot overwrite a deep result with a shallow one.
        """
        stmt = insert(PositionEval).values(
            position_key=key,
            engine_config_id=self._config_id,
            multipv=multipv,
            depth=evaluation.depth,
            lines=lines_to_json(evaluation.lines),
            updated_at=utcnow(),
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["position_key", "engine_config_id", "multipv"],
            set_={
                "depth": stmt.excluded.depth,
                "lines": stmt.excluded.lines,
                "updated_at": stmt.excluded.updated_at,
            },
            where=PositionEval.depth < stmt.excluded.depth,
        )
        self._session.execute(stmt)


class Evaluator:
    """Evaluate positions, consulting the cache before the engine."""

    def __init__(self, engine: Engine, cache: EvalCache) -> None:
        self._engine = engine
        self._cache = cache

    def evaluate(self, board: chess.Board, depth: int, multipv: int = 1) -> PositionEvaluation:
        return self.evaluate_many([board], depth, multipv)[0]

    def evaluate_many(
        self, boards: Sequence[chess.Board], depth: int, multipv: int = 1
    ) -> list[PositionEvaluation]:
        """Evaluate each board; one cache query covers the whole batch."""
        cacheable = [
            position_key(board)
            for board in boards
            if not board.is_game_over(claim_draw=False) and not is_history_sensitive(board)
        ]
        cached = self._cache.get_many(cacheable, depth, multipv) if cacheable else {}
        return [self._evaluate_one(board, depth, multipv, cached) for board in boards]

    def _evaluate_one(
        self,
        board: chess.Board,
        depth: int,
        multipv: int,
        cached: dict[str, PositionEvaluation],
    ) -> PositionEvaluation:
        terminal = terminal_evaluation(board, depth)
        if terminal is not None:
            return terminal
        if is_history_sensitive(board):
            # Keep the move stack so the engine sees repetitions.
            return self._engine.analyse(board, depth, multipv)
        key = position_key(board)
        if key not in cached:
            # Drop the move stack: the result must be valid for this position
            # in any game, since that is what the cache key promises.
            cached[key] = self._engine.analyse(board.copy(stack=False), depth, multipv)
            self._cache.put(key, cached[key], multipv)
        return cached[key]
