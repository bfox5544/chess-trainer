import pytest

from chess_trainer.analysis.clock import is_time_pressure, time_pressure_limit, time_spent


def test_time_spent_adds_the_increment_back() -> None:
    assert time_spent(300.0, 295.0, 0) == 5.0
    assert time_spent(180.0, 181.0, 2) == 1.0  # clock went up: 1s used, 2s added


def test_time_spent_is_never_negative_and_needs_both_clocks() -> None:
    assert time_spent(100.0, 100.4, 0) == 0.0
    assert time_spent(None, 100.0, 0) is None
    assert time_spent(100.0, None, 0) is None


@pytest.mark.parametrize(
    ("base", "expected"),
    [(600, 30.0), (300, 30.0), (180, 18.0), (60, 6.0), (None, None)],
)
def test_limit_scales_down_for_short_games(base: int | None, expected: float | None) -> None:
    assert time_pressure_limit(base, seconds=30, fraction=0.1) == expected


def test_is_time_pressure() -> None:
    assert is_time_pressure(29.0, 600, 30, 0.1) is True
    assert is_time_pressure(30.0, 600, 30, 0.1) is False
    assert is_time_pressure(20.0, 60, 30, 0.1) is False  # 20s is plenty in bullet
    assert is_time_pressure(5.0, 60, 30, 0.1) is True


def test_no_clock_data_means_unknown_not_false() -> None:
    assert is_time_pressure(None, 600, 30, 0.1) is None
    assert is_time_pressure(12.0, None, 30, 0.1) is None
