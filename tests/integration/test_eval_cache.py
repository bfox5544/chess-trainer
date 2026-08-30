import chess
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from chess_trainer.analysis.cache import (
    EvalCache,
    Evaluator,
    get_or_create_engine_config,
    position_key,
)
from chess_trainer.analysis.engine import EvalLine, PositionEvaluation
from chess_trainer.analysis.winprob import Eval
from chess_trainer.db.models import EngineConfig, PositionEval
from tests.fakes import FakeEngine, position_after

pytestmark = pytest.mark.integration

KEY = position_key(chess.Board())


def evaluation(depth: int, *cps: int) -> PositionEvaluation:
    return PositionEvaluation(depth, tuple(EvalLine(Eval(cp=cp), ("e2e4",)) for cp in cps))


@pytest.fixture
def cache(session: Session) -> EvalCache:
    config = get_or_create_engine_config(session, FakeEngine())
    return EvalCache(session, config.id)


def test_engine_config_is_registered_once_per_fingerprint(session: Session) -> None:
    first = get_or_create_engine_config(session, FakeEngine())
    again = get_or_create_engine_config(session, FakeEngine())
    newer = get_or_create_engine_config(session, FakeEngine(name="FakeFish 2"))
    assert first.id == again.id != newer.id
    assert session.scalar(select(func.count()).select_from(EngineConfig)) == 2


def test_hit_requires_at_least_the_requested_depth(cache: EvalCache) -> None:
    cache.put(KEY, evaluation(16, 25), multipv=1)
    assert cache.get_many([KEY], depth=16, multipv=1)[KEY].best.eval == Eval(cp=25)
    assert cache.get_many([KEY], depth=12, multipv=1)[KEY].depth == 16  # deeper is reused
    assert cache.get_many([KEY], depth=18, multipv=1) == {}


def test_only_a_deeper_search_overwrites(cache: EvalCache) -> None:
    cache.put(KEY, evaluation(16, 25), multipv=1)
    cache.put(KEY, evaluation(12, 99), multipv=1)  # shallower: ignored
    cache.put(KEY, evaluation(16, 98), multipv=1)  # same depth: ignored
    assert cache.get_many([KEY], 1, 1)[KEY] == evaluation(16, 25)
    cache.put(KEY, evaluation(20, 40), multipv=1)
    assert cache.get_many([KEY], 1, 1)[KEY] == evaluation(20, 40)


def test_multi_line_rows_answer_single_line_requests_but_not_vice_versa(
    cache: EvalCache,
) -> None:
    cache.put(KEY, evaluation(16, 30, 10), multipv=2)
    single = cache.get_many([KEY], depth=16, multipv=1)[KEY]
    assert single.lines == evaluation(16, 30).lines  # truncated to the best line
    assert len(cache.get_many([KEY], depth=16, multipv=2)[KEY].lines) == 2
    assert cache.get_many([KEY], depth=16, multipv=3) == {}


def test_deepest_qualifying_row_is_preferred(cache: EvalCache) -> None:
    cache.put(KEY, evaluation(14, 30, 10), multipv=2)
    cache.put(KEY, evaluation(20, 45), multipv=1)
    assert cache.get_many([KEY], depth=12, multipv=1)[KEY].best.eval == Eval(cp=45)
    assert cache.get_many([KEY], depth=12, multipv=2)[KEY].depth == 14


def test_evaluations_from_another_engine_config_are_invisible(session: Session) -> None:
    old = get_or_create_engine_config(session, FakeEngine(name="FakeFish 1"))
    new = get_or_create_engine_config(session, FakeEngine(name="FakeFish 2"))
    EvalCache(session, old.id).put(KEY, evaluation(30, 25), multipv=1)
    assert EvalCache(session, new.id).get_many([KEY], depth=10, multipv=1) == {}


def test_evaluator_only_calls_the_engine_on_a_miss(session: Session, cache: EvalCache) -> None:
    engine = FakeEngine()
    evaluator = Evaluator(engine, cache)
    board = position_after("e4", "e5")

    evaluator.evaluate(board, depth=12)
    evaluator.evaluate(board, depth=12)
    evaluator.evaluate(board, depth=10)
    assert len(engine.calls) == 1

    evaluator.evaluate(board, depth=14)  # deeper than cached
    evaluator.evaluate(board, depth=12, multipv=2)  # more lines than cached
    assert [(depth, multipv) for _, depth, multipv in engine.calls] == [(12, 1), (14, 1), (12, 2)]


def test_evaluator_shares_cache_across_transpositions(cache: EvalCache) -> None:
    engine = FakeEngine()
    evaluator = Evaluator(engine, cache)
    evaluator.evaluate(position_after("e4", "e5", "Nf3", "Nc6"), depth=12)
    evaluator.evaluate(position_after("Nf3", "Nc6", "e4", "e5"), depth=12)
    assert len(engine.calls) == 1
    assert engine.stacks == [0]  # analysed without history, so valid for any game


def test_history_sensitive_positions_bypass_the_cache(session: Session, cache: EvalCache) -> None:
    engine = FakeEngine()
    evaluator = Evaluator(engine, cache)
    repeated = position_after("Nf3", "Nf6", "Ng1", "Ng8")

    evaluator.evaluate(repeated, depth=12)
    evaluator.evaluate(repeated, depth=12)

    assert len(engine.calls) == 2  # never served from cache
    assert engine.stacks == [4, 4]  # engine was given the move history
    assert session.scalar(select(func.count()).select_from(PositionEval)) == 0


def test_terminal_positions_never_reach_the_engine(cache: EvalCache) -> None:
    engine = FakeEngine()
    mated = position_after("f3", "e5", "g4", "Qh4#")
    result = Evaluator(engine, cache).evaluate(mated, depth=12)
    assert result.best.eval == Eval.checkmate(chess.BLACK)
    assert engine.calls == []
