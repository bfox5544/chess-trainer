"""Clock-derived context for a move."""


def time_spent(previous_clock: float | None, clock: float | None, increment: float) -> float | None:
    """Seconds used on a move.

    PGN `%clk` values are recorded after the increment has been added, so the
    increment is added back. Clamped at zero to absorb rounding and lag
    compensation.
    """
    if previous_clock is None or clock is None:
        return None
    return max(0.0, previous_clock - clock + increment)


def time_pressure_limit(base_seconds: int | None, seconds: float, fraction: float) -> float | None:
    """Clock value below which a move counts as played under time pressure.

    min(seconds, fraction * base time): a flat 30s would label most of a
    1-minute bullet game as time pressure, so short games scale down.
    """
    if base_seconds is None:
        return None
    return min(seconds, fraction * base_seconds)


def is_time_pressure(
    clock: float | None, base_seconds: int | None, seconds: float, fraction: float
) -> bool | None:
    """None when the game has no usable clock data (e.g. correspondence)."""
    limit = time_pressure_limit(base_seconds, seconds, fraction)
    if clock is None or limit is None:
        return None
    return clock < limit
