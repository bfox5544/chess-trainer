from collections.abc import Callable

import chess

from chess_trainer.analysis.openings import Opening, OpeningBook, load_opening_book
from chess_trainer.analysis.replay import replay_pgn
from tests.fakes import position_after


def test_bundled_book_knows_common_openings() -> None:
    book = load_opening_book()
    assert len(book) > 3000
    sicilian = book.lookup(position_after("e4", "c5"))
    assert sicilian == Opening("B20", "Sicilian Defense")
    assert book.lookup(chess.Board()) is None


def test_lookup_is_by_position_so_transpositions_match() -> None:
    book = load_opening_book()
    via_e4 = book.lookup(position_after("e4", "e6", "d4", "d5"))
    via_d4 = book.lookup(position_after("d4", "e6", "e4", "d5"))
    assert via_e4 is not None and via_e4 == via_d4
    assert via_e4.family == "French Defense"


def test_family_is_the_name_before_the_colon() -> None:
    assert Opening("B90", "Sicilian Defense: Najdorf Variation").family == "Sicilian Defense"
    assert Opening("C50", "Italian Game").family == "Italian Game"


def test_deepest_match_wins_and_reports_where_theory_ended(
    load_pgn: Callable[[str], str],
) -> None:
    replay = replay_pgn(load_pgn("chesscom_opera_game"))
    match = load_opening_book().deepest_match(replay.boards)
    assert match is not None
    assert (match.opening.eco, match.opening.name) == ("C41", "Philidor Defense")
    assert match.ply == 5  # 1.e4 e5 2.Nf3 d6 3.d4; 3...Bg4 left the book


def test_no_match_returns_none() -> None:
    empty = OpeningBook({})
    assert empty.deepest_match([chess.Board(), position_after("e4")]) is None
