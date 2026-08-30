import chess
import pytest

from chess_trainer.analysis.winprob import CHECKMATE_CP, Eval, white_win_pct, win_pct


def test_equal_position_is_fifty_fifty() -> None:
    assert white_win_pct(Eval(cp=0)) == pytest.approx(50.0)


def test_known_points_on_the_lichess_curve() -> None:
    assert white_win_pct(Eval(cp=100)) == pytest.approx(59.1, abs=0.05)
    assert white_win_pct(Eval(cp=300)) == pytest.approx(75.1, abs=0.05)
    assert white_win_pct(Eval(cp=-300)) == pytest.approx(24.9, abs=0.05)


def test_curve_is_symmetric() -> None:
    for cp in (15, 120, 480, 999):
        assert white_win_pct(Eval(cp=cp)) + white_win_pct(Eval(cp=-cp)) == pytest.approx(100.0)


def test_centipawns_are_clamped_at_ten_pawns() -> None:
    assert white_win_pct(Eval(cp=1000)) == white_win_pct(Eval(cp=4000))
    assert white_win_pct(Eval(cp=4000)) < 100.0  # a big edge is still not a forced mate


def test_forced_mate_is_certain_whatever_its_length() -> None:
    assert white_win_pct(Eval(mate=1)) == white_win_pct(Eval(mate=12)) == 100.0
    assert white_win_pct(Eval(mate=-1)) == white_win_pct(Eval(mate=-12)) == 0.0


def test_delivered_checkmate() -> None:
    assert Eval.checkmate(chess.WHITE) == Eval(cp=CHECKMATE_CP)
    assert white_win_pct(Eval.checkmate(chess.WHITE)) == 100.0
    assert white_win_pct(Eval.checkmate(chess.BLACK)) == 0.0


def test_point_of_view_flip() -> None:
    evaluation = Eval(cp=300)  # White is better
    assert win_pct(evaluation, chess.WHITE) == pytest.approx(75.1, abs=0.05)
    assert win_pct(evaluation, chess.BLACK) == pytest.approx(24.9, abs=0.05)
    assert win_pct(Eval(mate=-2), chess.BLACK) == 100.0


def test_is_mate_for() -> None:
    assert Eval(mate=3).is_mate_for(chess.WHITE)
    assert not Eval(mate=3).is_mate_for(chess.BLACK)
    assert Eval(mate=-3).is_mate_for(chess.BLACK)
    assert Eval.checkmate(chess.BLACK).is_mate_for(chess.BLACK)
    assert not Eval(cp=900).is_mate_for(chess.WHITE)


@pytest.mark.parametrize("kwargs", [{}, {"cp": 10, "mate": 2}, {"mate": 0}])
def test_invalid_evals_are_rejected(kwargs: dict[str, int]) -> None:
    with pytest.raises(ValueError):
        Eval(**kwargs)
