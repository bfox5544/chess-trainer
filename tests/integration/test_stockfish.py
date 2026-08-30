"""Smoke test against a real Stockfish binary; skipped when it isn't installed."""

from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from chess_trainer.analysis.cache import terminal_evaluation
from chess_trainer.analysis.classify import Thresholds
from chess_trainer.analysis.engine import StockfishEngine
from chess_trainer.analysis.moves import GameContext, build_move_records
from chess_trainer.analysis.phase import game_phases
from chess_trainer.analysis.replay import replay_pgn
from chess_trainer.config import Settings
from chess_trainer.db.enums import Classification

pytestmark = pytest.mark.stockfish


@pytest.fixture(scope="module")
def stockfish() -> Iterator[StockfishEngine]:
    path = Settings().stockfish_path
    if not Path(path).exists():
        pytest.skip(f"no Stockfish binary at {path}")
    with StockfishEngine(path, threads=1, hash_mb=16) as engine:
        yield engine


def test_engine_reports_identity_and_lines(stockfish: StockfishEngine) -> None:
    assert stockfish.name.startswith("Stockfish")
    assert stockfish.eval_options == {}
    board = replay_pgn('[Result "*"]\n\n1. e4 e5 *').final_board
    result = stockfish.analyse(board, depth=8, multipv=2)
    assert result.depth >= 8
    assert len(result.lines) == 2 and all(line.pv for line in result.lines)
    assert result.best.eval.cp is not None and abs(result.best.eval.cp) < 150


def test_real_engine_finds_the_scholars_mate_blunder(
    stockfish: StockfishEngine, load_pgn: Callable[[str], str]
) -> None:
    replay = replay_pgn(load_pgn("lichess_scholars_mate"))
    evaluations = [
        terminal_evaluation(board, 10) or stockfish.analyse(board, depth=10, multipv=1)
        for board in replay.boards
    ]
    context = GameContext(Thresholds(), 0, 300, 0)
    records = build_move_records(replay.plies, evaluations, game_phases(replay.boards), context)

    blunder = records[5]  # 3...Nf6?? walks into Qxf7#
    assert blunder.classification is Classification.BLUNDER
    assert blunder.eval_after.mate == 1
    assert records[6].is_best  # 4.Qxf7# is the engine's move
    assert [r.san for r in records if r.classification is Classification.BLUNDER] == ["Nf6"]
