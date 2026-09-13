"""Puzzle rating and training focus: pure rules."""

import random
from collections import Counter

import pytest

from chess_trainer.db.enums import Phase, TimeClass
from chess_trainer.training.focus import (
    Focus,
    Group,
    MotifCount,
    Signals,
    allocate,
    build_foci,
    level_focus,
    opening_tag,
    phase_foci,
    tactic_focus,
)
from chess_trainer.training.rating import Rating, expected_score, seed_rating, update

START = Rating(1500, 250)


def test_equal_ratings_expect_half() -> None:
    assert expected_score(START, 1500, 80) == pytest.approx(0.5)
    assert expected_score(START, 1900, 80) < 0.2


def test_solving_raises_and_failing_lowers_the_rating() -> None:
    won = update(START, 1500, 80, True, min_deviation=70)
    lost = update(START, 1500, 80, False, min_deviation=70)
    assert won.rating > 1500 > lost.rating
    assert won.rating - 1500 == pytest.approx(1500 - lost.rating)
    assert won.deviation < START.deviation


def test_an_upset_moves_the_rating_more_than_an_expected_result() -> None:
    upset = update(START, 1900, 80, True, min_deviation=70).rating - 1500
    expected = update(START, 1100, 80, True, min_deviation=70).rating - 1500
    assert upset > expected > 0


def test_a_settled_rating_moves_less_and_keeps_a_floor() -> None:
    settled = Rating(1500, 70)
    after = update(settled, 1500, 80, True, min_deviation=70)
    assert after.rating - 1500 < update(START, 1500, 80, True, min_deviation=70).rating - 1500
    assert after.deviation == 70


def test_seed_is_the_median_game_rating() -> None:
    assert seed_rating([900, 1000, 1400], default=1500) == 1000
    assert seed_rating([], default=1500) == 1500
    assert seed_rating([100], default=1500) == 400


def test_tactic_focus_says_what_was_missed_and_allowed() -> None:
    focus = tactic_focus(MotifCount("fork", missed_games=6, allowed_games=1))
    assert focus is not None
    assert (focus.title, focus.theme) == ("Forks", "fork")
    assert focus.reason == "You missed a fork in 6 games and allowed a fork in 1 game."
    assert tactic_focus(MotifCount("fork", 0, 3)).reason == "You allowed a fork in 3 games."  # type: ignore[union-attr]


def test_one_game_is_not_a_pattern_and_unknown_themes_are_skipped() -> None:
    assert tactic_focus(MotifCount("fork", 1, 0)) is None
    assert tactic_focus(MotifCount("zugzwang", 9, 9)) is None


def test_opening_tag_matches_the_lichess_spelling() -> None:
    assert opening_tag("Petrov's Defense") == "Petrovs_Defense"
    assert opening_tag("Caro-Kann Defense") == "Caro-Kann_Defense"


def test_phases_need_a_real_share_of_the_errors() -> None:
    foci = phase_foci({Phase.OPENING: 5, Phase.MIDDLEGAME: 90, Phase.ENDGAME: 5})
    assert [f.key for f in foci] == ["middlegame"]
    assert foci[0].reason == "90% of your mistakes and blunders come in the middlegame."
    assert phase_foci({}) == []


def test_puzzle_length_follows_the_pace_of_your_games() -> None:
    assert level_focus({TimeClass.BLITZ: 8, TimeClass.RAPID: 2}).theme == "short"
    assert level_focus({TimeClass.RAPID: 9, TimeClass.BULLET: 1}).theme == "long"
    assert level_focus({TimeClass.BLITZ: 5, TimeClass.RAPID: 5}).theme is None
    assert level_focus({}).theme is None


def signals() -> Signals:
    return Signals(
        motifs=[MotifCount("fork", 4, 5), MotifCount("hangingPiece", 10, 30)],
        phase_errors={Phase.MIDDLEGAME: 10, Phase.ENDGAME: 10},
        openings=[("Italian Game", 12), ("Ruy Lopez", 2)],
        time_classes={TimeClass.BLITZ: 10},
    )


def test_foci_cover_every_kind_of_evidence() -> None:
    foci = build_foci(signals())
    assert [(f.group, f.key) for f in foci] == [
        (Group.TACTIC, "hangingPiece"),
        (Group.TACTIC, "fork"),
        (Group.OPENING, "Italian_Game"),
        (Group.PHASE, "middlegame"),
        (Group.PHASE, "endgame"),
        (Group.LEVEL, "short"),
    ]


def test_allocation_follows_the_group_shares() -> None:
    chosen = allocate(build_foci(signals()), 20, random.Random(3))
    groups = Counter(focus.group for focus in chosen)
    assert groups == {Group.TACTIC: 10, Group.OPENING: 4, Group.PHASE: 3, Group.LEVEL: 3}
    assert {f.key for f in chosen if f.group is Group.TACTIC} == {"hangingPiece", "fork"}


def test_an_empty_group_gives_its_share_to_your_level() -> None:
    level = Focus(Group.LEVEL, "any", "Puzzles at your level", "", 1.0)
    assert allocate([level], 5, random.Random(1)) == [level] * 5
    assert allocate([], 5, random.Random(1)) == []
