import pytest

from chess_trainer.db.enums import TimeClass
from chess_trainer.ingestion.timecontrol import parse_time_control


@pytest.mark.parametrize(
    ("raw", "base", "increment", "time_class"),
    [
        ("60", 60, 0, TimeClass.BULLET),
        ("15+0", 15, 0, TimeClass.BULLET),  # ultra-bullet folds into bullet
        ("120+1", 120, 1, TimeClass.BULLET),  # 160s estimated
        ("180", 180, 0, TimeClass.BLITZ),
        ("300+3", 300, 3, TimeClass.BLITZ),  # 420s estimated
        ("600", 600, 0, TimeClass.RAPID),
        ("900+10", 900, 10, TimeClass.RAPID),  # 1300s estimated
        ("1800+0", 1800, 0, TimeClass.CLASSICAL),
    ],
)
def test_live_time_controls(raw: str, base: int, increment: int, time_class: TimeClass) -> None:
    parsed = parse_time_control(raw)
    assert (parsed.base_seconds, parsed.increment_seconds) == (base, increment)
    assert parsed.time_class is time_class


@pytest.mark.parametrize("raw", ["-", "", None, "1/86400", "?", "40/7200:3600"])
def test_everything_else_is_correspondence(raw: str | None) -> None:
    parsed = parse_time_control(raw)
    assert parsed.time_class is TimeClass.CORRESPONDENCE
    assert parsed.base_seconds is None
