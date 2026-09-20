from dataclasses import dataclass, field

import chess

from chess_trainer.analysis.explain import Reason
from chess_trainer.db.enums import Classification, Color, Highlight
from chess_trainer.reports.key_moments import KeyMomentConfig, find_key_moments

CONFIG = KeyMomentConfig(max_moments=3, min_swing=10.0)
GOOD, MISTAKE, BLUNDER = Classification.GOOD, Classification.MISTAKE, Classification.BLUNDER


@dataclass
class Row:
    """A stored move with only what key moments read."""

    ply: int
    san: str
    uci: str
    classification: Classification = GOOD
    win_pct_before: float = 50.0
    win_pct_after: float = 50.0
    win_pct_loss: float = 0.0
    best_move_uci: str | None = None
    best_move_san: str | None = None
    best_line: list[str] = field(default_factory=list)
    highlight: Highlight | None = None
    second_best_win_pct: float | None = None
    is_forced: bool = False
    fen_before: str = chess.STARTING_FEN

    @property
    def color(self) -> Color:
        return Color.WHITE if self.ply % 2 == 0 else Color.BLACK

    @property
    def move_number(self) -> int:
        return self.ply // 2 + 1


def game(*rows: Row) -> list[Row]:
    return list(rows)


def moments(rows: list[Row], colors: set[Color] = {Color.WHITE}, config: KeyMomentConfig = CONFIG):  # noqa: B006
    return find_key_moments(rows, [[] for _ in rows], colors, config)


def test_a_mistake_is_a_moment_with_the_engine_move_to_find() -> None:
    rows = game(
        Row(0, "e4", "e2e4"),
        Row(1, "e5", "e7e5"),
        Row(2, "Qh5", "d1h5", MISTAKE, 50, 38, 12, "g1f3", "Nf3", ["g1f3", "b8c6"]),
    )
    (moment,) = moments(rows)
    assert (moment.kind, moment.title, moment.ply) == ("mistake", "Your mistake", 2)
    assert (moment.answer_uci, moment.answer_san, moment.answer_line) == (
        "g1f3",
        "Nf3",
        ["g1f3", "b8c6"],
    )
    assert (moment.previous_san, moment.played_san) == ("e5", "Qh5")
    assert moment.text == "Qh5 dropped your winning chances from 50% to 38%. Nf3 was better."
    # The opponent's moves are never moments of their own.
    assert moments(rows, {Color.BLACK}) == []


def test_after_an_opponent_error_a_mistake_is_a_missed_chance_and_a_good_move_punishes() -> None:
    opponent_blunder = Row(1, "f6", "f7f6", BLUNDER, 50, 20, 30)
    missed = moments(
        game(opponent_blunder, Row(2, "d3", "d2d3", MISTAKE, 80, 55, 25, "d1h5", "Qh5+"))
    )
    assert [(m.kind, m.title) for m in missed] == [("missed", "Missed chance")]

    (punished,) = moments(
        game(opponent_blunder, Row(2, "Qh5+", "d1h5", GOOD, 80, 80, 0, "d1h5", "Qh5+"))
    )
    assert (punished.kind, punished.swing, punished.win_pct_before) == ("punished", 30, 50)
    assert punished.text == (
        "Your opponent's f6 was a blunder, and you found Qh5+: "
        "your winning chances went from 50% to 80%."
    )


def test_taking_back_a_hung_piece_is_not_a_punishment() -> None:
    board = chess.Board()
    for san in ["e4", "e5", "Nf3", "Qf6", "Nc3", "Qxf3"]:  # 3...Qxf3?? hangs the queen
        board.push_san(san)
    queen_hangs = Row(5, "Qxf3", "f6f3", BLUNDER, 50, 5, 45)
    recapture = Row(6, "gxf3", "g2f3", GOOD, 95, 95, 0, "g2f3", "gxf3", fen_before=board.fen())
    assert moments(game(queen_hangs, recapture)) == []


def test_highlights_qualify_and_the_biggest_swings_are_kept_in_game_order() -> None:
    reasons = [Reason("great", "The only good move here.")]
    rows = game(
        Row(0, "a3", "a2a3", MISTAKE, 50, 39, 11, "e2e4", "e4"),
        Row(2, "b3", "b2b3", BLUNDER, 50, 20, 30, "e2e4", "e4"),
        Row(4, "c3", "c2c3", MISTAKE, 50, 35, 15, "e2e4", "e4"),
        Row(6, "Nf3", "g1f3", highlight=Highlight.GREAT, second_best_win_pct=25.0),
        Row(
            8,
            "Bxf7+",
            "f1f7",
            highlight=Highlight.BRILLIANT,
            best_move_uci="e2e4",
            best_move_san="e4",
        ),
        Row(10, "h3", "h2h3", is_forced=True, classification=BLUNDER, win_pct_loss=40),
    )
    explanations = [[], [], [], reasons, [], []]
    found = find_key_moments(rows, explanations, {Color.WHITE}, CONFIG)
    # Brilliant (always first), b3 (30), great (25 = 50 - 25); a3 and c3 lose
    # out, and a forced move is never a moment.
    assert [m.played_san for m in found] == ["b3", "Nf3", "Bxf7+"]
    great, brilliant = found[1], found[2]
    assert (great.title, great.text) == ("Great move", "The only good move here.")
    # A brilliant sacrifice is the move to find, even if the engine liked another a hair more.
    assert (brilliant.answer_uci, brilliant.answer_line) == ("f1f7", ["f1f7"])


def test_small_swings_are_not_moments() -> None:
    rows = game(Row(0, "a3", "a2a3", MISTAKE, 50, 41, 9.5, "e2e4", "e4"))
    assert moments(rows) == []
