"""Key moments: the few turning points of a game worth reviewing.

Pure: works on the stored move rows of one game. A moment is always one of
the user's own moves, because each becomes a "find the move" exercise from
the position before it:

- **mistake**: the user's mistake or blunder.
- **missed**: the same, right after the opponent's mistake or blunder: the
  chance they gave was let go.
- **punished**: the opponent's mistake or blunder, answered with a good move
  (unless the answer just takes the piece that moved: no exercise in that).
- **great** / **brilliant**: a move marked so by the analysis.

Moments are ranked by the winning chances at stake (win-% points: what the
mistake cost, what the opponent's error offered, or how much worse the second
best move was) and the top `max_moments` with at least `min_swing` are kept,
in game order. Brilliant moves always qualify: they are rare and the point of
the exercise.
"""

from collections.abc import Collection, Sequence
from dataclasses import dataclass, field
from typing import Protocol

import chess

from chess_trainer.analysis.explain import Reason
from chess_trainer.db.enums import Classification, Color, Highlight

ERRORS = (Classification.MISTAKE, Classification.BLUNDER)
BRILLIANT_SWING = 100.0  # ranks first


@dataclass(frozen=True)
class KeyMomentConfig:
    max_moments: int = 4
    min_swing: float = 10.0  # win-% points


class MoveRow(Protocol):
    """The stored move fields a moment needs (a `MoveAnalysis` row)."""

    ply: int
    move_number: int
    color: Color
    san: str
    uci: str
    fen_before: str
    best_move_uci: str | None
    best_move_san: str | None
    best_line: list[str]
    win_pct_before: float
    win_pct_after: float
    win_pct_loss: float
    classification: Classification
    is_forced: bool
    highlight: Highlight | None
    second_best_win_pct: float | None


@dataclass(frozen=True)
class KeyMoment:
    ply: int  # the user's move
    move_number: int
    color: Color
    kind: str  # mistake | missed | punished | great | brilliant
    title: str
    text: str
    fen: str  # the position to find the move in
    played_uci: str
    played_san: str
    answer_uci: str  # the move to find
    answer_san: str
    answer_line: list[str]  # UCI, from `fen`, starting with the answer
    previous_uci: str | None  # the opponent's move that led here
    previous_san: str | None
    win_pct_before: float  # the user's, before the moment (before the opponent's error, if any)
    win_pct_after: float  # the user's, after their move
    swing: float
    explanation: list[Reason] = field(default_factory=list)


def pct(value: float) -> str:
    return f"{round(value)}%"


def takes_what_just_moved(move: MoveRow, previous: MoveRow) -> bool:
    """The answer captures on the square the opponent's move landed on."""
    board = chess.Board(move.fen_before)
    answer = chess.Move.from_uci(move.best_move_uci or move.uci)
    return answer.to_square == chess.parse_square(previous.uci[2:4]) and board.is_capture(answer)


def moment_kind(move: MoveRow, previous: MoveRow | None) -> tuple[str, float] | None:
    """What kind of moment `move` is, and its swing; None if it is not one."""
    opponent_erred = previous is not None and previous.classification in ERRORS
    if move.highlight is Highlight.BRILLIANT:
        return "brilliant", BRILLIANT_SWING
    if move.highlight is Highlight.GREAT:
        second = move.second_best_win_pct
        return "great", move.win_pct_after - second if second is not None else 0.0
    if move.classification in ERRORS:
        return ("missed" if opponent_erred else "mistake"), move.win_pct_loss
    if opponent_erred and move.classification is Classification.GOOD:
        assert previous is not None
        if takes_what_just_moved(move, previous):
            return None  # taking a hung piece back is no exercise
        return "punished", previous.win_pct_loss
    return None


def describe(
    kind: str, move: MoveRow, previous: MoveRow | None, reasons: list[Reason]
) -> tuple[str, str]:
    """Title and one-paragraph summary."""
    best = move.best_move_san or move.san
    if kind == "mistake":
        return (
            f"Your {move.classification.value}",
            f"{move.san} dropped your winning chances from {pct(move.win_pct_before)} to "
            f"{pct(move.win_pct_after)}. {best} was better.",
        )
    if kind == "missed":
        assert previous is not None
        return (
            "Missed chance",
            f"Your opponent's {previous.san} gave you a chance, but {move.san} let it go: "
            f"your winning chances fell from {pct(move.win_pct_before)} to "
            f"{pct(move.win_pct_after)}. {best} kept the advantage.",
        )
    if kind == "punished":
        assert previous is not None
        return (
            "You punished it",
            f"Your opponent's {previous.san} was a {previous.classification.value}, and you "
            f"found {move.san}: your winning chances went from "
            f"{pct(100 - previous.win_pct_before)} to {pct(move.win_pct_after)}.",
        )
    # Great and brilliant: the analysis already says why, as the first reason.
    title = "Brilliant move" if kind == "brilliant" else "Great move"
    return title, reasons[0].text if reasons else title + "."


def answer_of(kind: str, move: MoveRow) -> tuple[str, str, list[str]]:
    """The move to find: the engine's choice, except that a brilliant
    sacrifice (which may be a hair short of it) is the move itself."""
    if kind == "brilliant" or not move.best_move_uci or not move.best_move_san:
        line = move.best_line if move.best_line[:1] == [move.uci] else [move.uci]
        return move.uci, move.san, line
    return move.best_move_uci, move.best_move_san, move.best_line


def build_moment(
    kind: str, swing: float, move: MoveRow, previous: MoveRow | None, reasons: list[Reason]
) -> KeyMoment:
    title, text = describe(kind, move, previous, reasons)
    answer_uci, answer_san, line = answer_of(kind, move)
    before = (
        100 - previous.win_pct_before if kind == "punished" and previous else move.win_pct_before
    )
    return KeyMoment(
        ply=move.ply,
        move_number=move.move_number,
        color=move.color,
        kind=kind,
        title=title,
        text=text,
        fen=move.fen_before,
        played_uci=move.uci,
        played_san=move.san,
        answer_uci=answer_uci,
        answer_san=answer_san,
        answer_line=list(line),
        previous_uci=previous.uci if previous else None,
        previous_san=previous.san if previous else None,
        win_pct_before=round(before, 1),
        win_pct_after=round(move.win_pct_after, 1),
        swing=round(swing, 1),
        explanation=reasons,
    )


def find_key_moments(
    moves: Sequence[MoveRow],
    explanations: Sequence[list[Reason]],
    user_colors: Collection[Color],
    config: KeyMomentConfig,
) -> list[KeyMoment]:
    """`explanations` is parallel to `moves` (as in the game report)."""
    found: list[KeyMoment] = []
    for index, move in enumerate(moves):
        if move.color not in user_colors or move.is_forced:
            continue
        previous = moves[index - 1] if index > 0 else None
        if previous is not None and previous.ply != move.ply - 1:
            previous = None
        kind = moment_kind(move, previous)
        if kind is None or kind[1] < config.min_swing:
            continue
        found.append(build_moment(kind[0], kind[1], move, previous, explanations[index]))
    top = sorted(found, key=lambda moment: (-moment.swing, moment.ply))[: config.max_moments]
    return sorted(top, key=lambda moment: moment.ply)
