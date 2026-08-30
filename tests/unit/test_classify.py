import chess
import pytest

from chess_trainer.analysis.classify import Thresholds, classify, win_pct_loss
from chess_trainer.analysis.winprob import Eval
from chess_trainer.db.enums import Classification

T = Thresholds()


def label(before: Eval, after: Eval, mover: chess.Color = chess.WHITE) -> Classification:
    return classify(win_pct_loss(before, after, mover, played_best=False, forced=False), T)


@pytest.mark.parametrize(
    ("loss", "expected"),
    [
        (0.0, Classification.GOOD),
        (4.99, Classification.GOOD),
        (5.0, Classification.INACCURACY),
        (9.99, Classification.INACCURACY),
        (10.0, Classification.MISTAKE),
        (14.99, Classification.MISTAKE),
        (15.0, Classification.BLUNDER),
        (100.0, Classification.BLUNDER),
    ],
)
def test_threshold_boundaries(loss: float, expected: Classification) -> None:
    assert classify(loss, T) is expected


def test_thresholds_are_configurable() -> None:
    strict = Thresholds(inaccuracy=2, mistake=4, blunder=6)
    assert classify(5.0, strict) is Classification.MISTAKE


def test_same_centipawn_loss_counts_less_in_a_decided_position() -> None:
    """The reason for win-probability thresholds: both moves drop 3 pawns."""
    assert label(Eval(cp=100), Eval(cp=-200)) is Classification.BLUNDER
    assert label(Eval(cp=1000), Eval(cp=700)) is Classification.GOOD


def test_loss_is_measured_from_the_movers_side() -> None:
    # Eval rises for White, which is a loss for Black, who just moved.
    assert label(Eval(cp=-100), Eval(cp=200), chess.BLACK) is Classification.BLUNDER
    assert label(Eval(cp=-100), Eval(cp=200), chess.WHITE) is Classification.GOOD


def test_slower_mate_or_huge_edge_instead_of_mate_is_not_an_error() -> None:
    assert label(Eval(mate=2), Eval(mate=7)) is Classification.GOOD
    assert label(Eval(mate=2), Eval(cp=1500)) is Classification.GOOD


def test_throwing_away_a_forced_mate_for_a_small_edge_is_a_blunder() -> None:
    assert label(Eval(mate=2), Eval(cp=150)) is Classification.BLUNDER


def test_walking_into_mate_is_a_blunder_even_when_already_worse() -> None:
    assert label(Eval(cp=-150), Eval(mate=-1)) is Classification.BLUNDER


def test_walking_into_mate_when_already_lost_costs_little() -> None:
    assert label(Eval(cp=-950), Eval(mate=-3)) is Classification.GOOD


def test_delivering_checkmate_costs_nothing() -> None:
    assert label(Eval(mate=1), Eval.checkmate(chess.WHITE)) is Classification.GOOD


def test_playing_the_best_move_never_loses_anything() -> None:
    # Before/after are searched separately and can disagree; that is noise.
    loss = win_pct_loss(Eval(cp=50), Eval(cp=-80), chess.WHITE, played_best=True, forced=False)
    assert loss == 0.0


def test_forced_move_never_loses_anything() -> None:
    loss = win_pct_loss(Eval(cp=0), Eval(mate=-1), chess.WHITE, played_best=False, forced=True)
    assert loss == 0.0


def test_apparent_gain_is_clamped_to_zero() -> None:
    assert win_pct_loss(Eval(cp=0), Eval(cp=90), chess.WHITE, played_best=False, forced=False) == 0
