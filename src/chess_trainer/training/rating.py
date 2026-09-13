"""Puzzle rating: Glicko-1, one puzzle at a time. Pure.

A puzzle is an opponent with a known rating and deviation (Lichess publishes
both). Solving it cleanly is a win, anything else a loss, the same rule
Lichess uses. Glicko rather than Elo because the deviation says how sure the
rating is: it starts wide, so the first few puzzles move a seeded rating a
long way, and narrows as results come in.

Reference: Glickman, "The Glicko system" (1995).
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass
from statistics import median

Q = math.log(10) / 400
# Ratings outside this range have no puzzles to match.
MIN_RATING = 400.0
MAX_RATING = 3000.0


@dataclass(frozen=True)
class Rating:
    rating: float
    deviation: float


def g(deviation: float) -> float:
    """How much an opponent's uncertainty discounts a result."""
    return 1 / math.sqrt(1 + 3 * (Q * deviation) ** 2 / math.pi**2)


def expected_score(player: Rating, puzzle_rating: float, puzzle_deviation: float) -> float:
    """Probability that the player solves the puzzle."""
    exponent = -g(puzzle_deviation) * (player.rating - puzzle_rating) / 400
    return 1 / (1 + 10**exponent)


def update(
    player: Rating,
    puzzle_rating: float,
    puzzle_deviation: float,
    solved: bool,
    min_deviation: float,
) -> Rating:
    """The player's rating after one puzzle. The deviation never falls below
    `min_deviation`, so the rating keeps responding however many puzzles
    have been played."""
    weight = g(puzzle_deviation)
    expected = expected_score(player, puzzle_rating, puzzle_deviation)
    information = (Q * weight) ** 2 * expected * (1 - expected)  # 1 / d^2
    precision = 1 / player.deviation**2 + information
    rating = player.rating + Q / precision * weight * ((1.0 if solved else 0.0) - expected)
    deviation = max(min_deviation, math.sqrt(1 / precision))
    return Rating(min(MAX_RATING, max(MIN_RATING, rating)), deviation)


def seed_rating(game_ratings: Sequence[float], default: float) -> float:
    """A starting point from recent game ratings: their median, or `default`
    when there are none."""
    if not game_ratings:
        return default
    return min(MAX_RATING, max(MIN_RATING, float(median(game_ratings))))
