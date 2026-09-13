"""What a user should train, and how a set of puzzles is split between it. Pure.

Three kinds of evidence become "focus areas", each matching a filter on the
Lichess puzzle database:

- tactics the user missed or allowed in their own games (from mistakes),
- the openings they play (playstyle),
- the game phases where their mistakes happen (from mistakes),

plus puzzles at their level with no other filter, whose length follows the
time controls they play (playstyle). Every focus carries the reason it was
chosen, in words, so a recommendation can always say why.
"""

import math
import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum

from chess_trainer.db.enums import Phase, TimeClass


class Group(StrEnum):
    TACTIC = "tactic"
    OPENING = "opening"
    PHASE = "phase"
    LEVEL = "level"


# Share of a set of puzzles each group gets. A group with nothing in it
# (no analyzed games, no matching puzzles) gives its share to LEVEL.
GROUP_SHARE = {Group.TACTIC: 0.5, Group.OPENING: 0.2, Group.PHASE: 0.15, Group.LEVEL: 0.15}
MAX_TACTICS = 5
MAX_OPENINGS = 4
# One game is an accident; a pattern needs at least this many.
MIN_MOTIF_GAMES = 2
MIN_OPENING_GAMES = 3
# A phase is worth training when it holds at least this share of the errors.
MIN_PHASE_SHARE = 0.15
# Above this share of games, a kind of time control counts as "what you play".
PACE_SHARE = 0.6
FAST = (TimeClass.BULLET, TimeClass.BLITZ)

# theme -> (title, "missed ...", "allowed ...")
TACTICS: dict[str, tuple[str, str, str]] = {
    "hangingPiece": ("Hanging pieces", "missed a free piece", "left a piece hanging"),
    "fork": ("Forks", "missed a fork", "allowed a fork"),
    "pin": ("Pins", "missed a pin", "walked into a pin"),
    "skewer": ("Skewers", "missed a skewer", "allowed a skewer"),
    "discoveredAttack": (
        "Discovered attacks",
        "missed a discovered attack",
        "allowed a discovered attack",
    ),
    "mateIn1": ("Mate in one", "missed a mate in one", "allowed a mate in one"),
    "mateIn2": ("Mate in two", "missed a mate in two", "allowed a mate in two"),
    "mateIn3": ("Mate in three", "missed a mate in three", "allowed a mate in three"),
    "mate": ("Checkmates", "missed a forced mate", "allowed a forced mate"),
    "backRankMate": ("Back-rank mates", "missed a back-rank mate", "allowed a back-rank mate"),
    "promotion": ("Promotions", "missed a promotion", "allowed a promotion"),
}


@dataclass(frozen=True)
class MotifCount:
    theme: str
    missed_games: int  # games in which the user had this tactic and missed it
    allowed_games: int  # games in which the user's move allowed it


@dataclass(frozen=True)
class Signals:
    """Everything known about the user that shapes their training."""

    motifs: Sequence[MotifCount]
    phase_errors: Mapping[Phase, int]  # mistakes and blunders per phase
    openings: Sequence[tuple[str, int]]  # (opening family, games)
    time_classes: Mapping[TimeClass, int]  # games per time control


@dataclass(frozen=True)
class Focus:
    group: Group
    key: str  # unique within the group
    title: str
    reason: str
    weight: float
    theme: str | None = None  # library filter: puzzles with this theme
    opening: str | None = None  # library filter: puzzles with this opening tag


def games(count: int) -> str:
    return f"{count} game" if count == 1 else f"{count} games"


def opening_tag(family: str) -> str:
    """Our opening family name as the Lichess puzzle database tags it:
    "Petrov's Defense" -> "Petrovs_Defense"."""
    return family.replace("'", "").replace(" ", "_")


def tactic_focus(count: MotifCount) -> Focus | None:
    total = count.missed_games + count.allowed_games
    if count.theme not in TACTICS or total < MIN_MOTIF_GAMES:
        return None
    title, missed, allowed = TACTICS[count.theme]
    parts = []
    if count.missed_games:
        parts.append(f"{missed} in {games(count.missed_games)}")
    if count.allowed_games:
        parts.append(f"{allowed} in {games(count.allowed_games)}")
    # Square root: the commonest error should lead, not crowd out the rest.
    return Focus(
        Group.TACTIC,
        count.theme,
        title,
        f"You {' and '.join(parts)}.",
        math.sqrt(total),
        theme=count.theme,
    )


def tactic_foci(motifs: Sequence[MotifCount]) -> list[Focus]:
    found = [focus for count in motifs if (focus := tactic_focus(count))]
    return sorted(found, key=lambda f: (-f.weight, f.key))[:MAX_TACTICS]


def opening_foci(openings: Sequence[tuple[str, int]]) -> list[Focus]:
    played = sorted(openings, key=lambda item: (-item[1], item[0]))
    return [
        Focus(
            Group.OPENING,
            opening_tag(family),
            family,
            f"You play the {family} ({games(count)}).",
            math.sqrt(count),
            opening=opening_tag(family),
        )
        for family, count in played[:MAX_OPENINGS]
        if count >= MIN_OPENING_GAMES
    ]


def phase_foci(phase_errors: Mapping[Phase, int]) -> list[Focus]:
    total = sum(phase_errors.values())
    if not total:
        return []
    found = []
    for phase in Phase:
        share = phase_errors.get(phase, 0) / total
        if share < MIN_PHASE_SHARE:
            continue
        found.append(
            Focus(
                Group.PHASE,
                phase.value,
                phase.value.capitalize(),
                f"{round(100 * share)}% of your mistakes and blunders come in the {phase.value}.",
                share,
                theme=phase.value,
            )
        )
    return found


def level_focus(time_classes: Mapping[TimeClass, int]) -> Focus:
    """Puzzles at the user's rating. Their length follows the pace of the
    games the user plays; with no clear pace, any length."""
    total = sum(time_classes.values())
    fast = sum(time_classes.get(tc, 0) for tc in FAST)
    if total and fast / total >= PACE_SHARE:
        return Focus(
            Group.LEVEL,
            "short",
            "Quick tactics at your level",
            "You mostly play fast games, where short tactics decide the result.",
            1.0,
            theme="short",
        )
    if total and (total - fast) / total >= PACE_SHARE:
        return Focus(
            Group.LEVEL,
            "long",
            "Longer calculations at your level",
            "You mostly play slower games, where there is time to calculate further.",
            1.0,
            theme="long",
        )
    return Focus(
        Group.LEVEL,
        "any",
        "Puzzles at your level",
        "A mix of everything, rated close to you.",
        1.0,
    )


def build_foci(signals: Signals) -> list[Focus]:
    return [
        *tactic_foci(signals.motifs),
        *opening_foci(signals.openings),
        *phase_foci(signals.phase_errors),
        level_focus(signals.time_classes),
    ]


def allocate(foci: Sequence[Focus], count: int, rng: random.Random) -> list[Focus]:
    """Which focus each of `count` puzzles trains, in shuffled order.

    Each group first gets the whole puzzles its share is worth; what is left
    over is drawn at random by share, so one puzzle at a time still follows
    the shares on average. Within a group a focus is drawn by weight.
    """
    by_group: dict[Group, list[Focus]] = {group: [] for group in Group}
    for focus in foci:
        by_group[focus.group].append(focus)
    if not by_group[Group.LEVEL]:
        return []
    shares = {group: GROUP_SHARE[group] for group in Group if by_group[group]}
    shares[Group.LEVEL] += 1.0 - sum(shares.values())
    groups: list[Group] = []
    for group, share in shares.items():
        groups += [group] * math.floor(share * count)
    groups += rng.choices(list(shares), weights=list(shares.values()), k=count - len(groups))
    chosen = [
        rng.choices(by_group[group], weights=[f.weight for f in by_group[group]])[0]
        for group in groups
    ]
    rng.shuffle(chosen)
    return chosen
