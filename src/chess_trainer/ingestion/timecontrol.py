"""Parse PGN `TimeControl` values into one cross-platform time class.

Lichess and Chess.com draw the bullet/blitz/rapid lines in slightly different
places. To make filters and reports mean the same thing for both, every game
is classified with a single formula (Lichess's): estimated duration =
base + 40 * increment. Ultra-bullet is folded into bullet.
"""

from dataclasses import dataclass

from chess_trainer.db.enums import TimeClass

BULLET_MAX_SECONDS = 180
BLITZ_MAX_SECONDS = 480
RAPID_MAX_SECONDS = 1500


@dataclass(frozen=True)
class TimeControl:
    base_seconds: int | None
    increment_seconds: int | None
    time_class: TimeClass


CORRESPONDENCE = TimeControl(None, None, TimeClass.CORRESPONDENCE)


def classify_duration(base_seconds: int, increment_seconds: int) -> TimeClass:
    estimated = base_seconds + 40 * increment_seconds
    if estimated < BULLET_MAX_SECONDS:
        return TimeClass.BULLET
    if estimated < BLITZ_MAX_SECONDS:
        return TimeClass.BLITZ
    if estimated < RAPID_MAX_SECONDS:
        return TimeClass.RAPID
    return TimeClass.CLASSICAL


def parse_time_control(raw: str | None) -> TimeControl:
    """Parse 'base+inc' or 'base'. Anything else is treated as correspondence.

    That covers '-' (Lichess correspondence/unlimited) and '1/86400'
    (Chess.com daily: one move per N seconds).
    """
    if not raw:
        return CORRESPONDENCE
    base_text, _, increment_text = raw.partition("+")
    if not base_text.isdigit() or (increment_text and not increment_text.isdigit()):
        return CORRESPONDENCE
    base, increment = int(base_text), int(increment_text or 0)
    return TimeControl(base, increment, classify_duration(base, increment))
