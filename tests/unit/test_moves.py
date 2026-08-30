"""Move records built from a real PGN and hand-written evaluations."""

from collections.abc import Callable

import pytest

from chess_trainer.analysis.cache import terminal_evaluation
from chess_trainer.analysis.classify import Thresholds
from chess_trainer.analysis.engine import EvalLine, PositionEvaluation
from chess_trainer.analysis.moves import (
    GameContext,
    MoveRecord,
    build_move_record,
    build_move_records,
)
from chess_trainer.analysis.phase import game_phases
from chess_trainer.analysis.replay import replay_pgn
from chess_trainer.analysis.winprob import Eval
from chess_trainer.db.enums import Classification, Color, Phase
from tests.fakes import FakeEngine, scholars_mate_script


@pytest.fixture
def records(load_pgn: Callable[[str], str]) -> list[MoveRecord]:
    replay = replay_pgn(load_pgn("lichess_scholars_mate"))
    engine = FakeEngine(scholars_mate_script())
    evaluations = [engine.analyse(board, 12, 1) for board in replay.boards[:-1]]
    # The final position is checkmate, which is scored from the rules.
    mate = terminal_evaluation(replay.final_board, 12)
    assert mate is not None
    evaluations.append(mate)
    context = GameContext(Thresholds(), opening_ply=3, base_seconds=300, increment_seconds=0)
    return build_move_records(replay.plies, evaluations, game_phases(replay.boards), context)


def test_one_record_per_move_with_colors_and_numbers(records: list[MoveRecord]) -> None:
    assert [r.san for r in records] == ["e4", "e5", "Bc4", "Nc6", "Qh5", "Nf6", "Qxf7#"]
    assert [r.color for r in records[:2]] == [Color.WHITE, Color.BLACK]
    assert [r.move_number for r in records] == [1, 1, 2, 2, 3, 3, 4]
    assert all(r.phase is Phase.OPENING for r in records)


def test_the_blunder_is_found_and_measured_from_blacks_side(records: list[MoveRecord]) -> None:
    blunder = records[5]  # 3...Nf6??
    assert blunder.classification is Classification.BLUNDER
    assert (blunder.best_move_uci, blunder.best_move_san) == ("g7g6", "g6")
    assert blunder.eval_before == Eval(cp=-30)
    assert blunder.eval_after == Eval(mate=1)
    assert blunder.win_pct_before == pytest.approx(52.8, abs=0.1)  # Black slightly better
    assert blunder.win_pct_after == 0.0
    assert blunder.win_pct_loss == pytest.approx(52.8, abs=0.1)
    assert not blunder.is_best


def test_the_mating_move_is_best_and_costs_nothing(records: list[MoveRecord]) -> None:
    mate = records[6]
    assert mate.is_best and mate.classification is Classification.GOOD
    assert mate.eval_after == Eval.checkmate(True)
    assert mate.win_pct_after == 100.0


def test_only_the_blunder_is_flagged(records: list[MoveRecord]) -> None:
    flagged = [r.san for r in records if r.classification is not Classification.GOOD]
    assert flagged == ["Nf6"]


def test_book_moves_are_those_before_the_opening_ply(records: list[MoveRecord]) -> None:
    assert [r.in_book for r in records] == [True, True, True, False, False, False, False]


def test_clocks_and_time_spent_are_tracked_per_side(records: list[MoveRecord]) -> None:
    assert [r.clock_remaining_s for r in records] == [300, 300, 298, 297, 295, 267, 293]
    # Black: 300 -> 300 -> 297 -> 267; the blunder took 30 seconds.
    assert [r.time_spent_s for r in records if r.color is Color.BLACK] == [0, 3, 30]
    assert [r.time_spent_s for r in records if r.color is Color.WHITE] == [0, 2, 3, 2]


def test_forced_move_is_flagged_and_never_an_error() -> None:
    # White is in check and capturing the queen is the only legal move.
    pgn = '[SetUp "1"]\n[FEN "k7/8/8/8/8/8/6q1/7K w - - 0 1"]\n\n1. Kxg2 *'
    replay = replay_pgn(pgn)
    # Pretend the forced move is terrible and not the engine's choice.
    before = PositionEvaluation(8, (EvalLine(Eval(cp=0), ()),))
    after = PositionEvaluation(8, (EvalLine(Eval(mate=-1), ("a8a7",)),))
    context = GameContext(Thresholds(), 0, None, None)
    phases = game_phases(replay.boards)
    record = build_move_record(replay.plies[0], before, after, phases[0], None, context)
    assert record.san == "Kxg2" and record.is_forced and not record.is_best
    assert record.win_pct_loss == 0.0 and record.classification is Classification.GOOD
    assert record.clock_remaining_s is None and record.time_spent_s is None
