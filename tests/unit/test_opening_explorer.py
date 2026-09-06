import chess

from chess_trainer.analysis.openings import Opening, OpeningBook
from chess_trainer.reports.opening_explorer import entry_line, main_line


def position(*sans: str) -> str:
    board = chess.Board()
    for san in sans:
        board.push_san(san)
    return board.epd()


def ucis(*sans: str) -> list[str]:
    board = chess.Board()
    moves = []
    for san in sans:
        moves.append(board.push_san(san).uci())
    return moves


BOOK = OpeningBook(
    {
        position("e4"): Opening("B00", "King's Pawn Game"),
        position("e4", "c6"): Opening("B10", "Caro-Kann Defense"),
        position("e4", "c6", "d4", "d5", "e5"): Opening(
            "B12", "Caro-Kann Defense: Advance Variation"
        ),
        position("e4", "c6", "Nc3"): Opening("B10", "Caro-Kann Defense: Two Knights Attack"),
        position("c4", "c6", "e4"): Opening("B10", "Caro-Kann Defense: Accelerated Panov Attack"),
    }
)


def test_entry_line_stops_at_the_family_root() -> None:
    game = ucis("e4", "c6", "d4", "d5", "e5", "Bf5")
    assert entry_line(game, "Caro-Kann Defense", BOOK) == ucis("e4", "c6")


def test_entry_line_falls_back_to_the_first_position_of_the_family() -> None:
    game = ucis("c4", "c6", "e4", "d5")
    assert entry_line(game, "Caro-Kann Defense", BOOK) == ucis("c4", "c6", "e4")


def test_entry_line_is_none_when_the_family_never_appears() -> None:
    assert entry_line(ucis("d4", "d5"), "Caro-Kann Defense", BOOK) is None
    assert entry_line(["e2e4", "zzzz"], "Caro-Kann Defense", BOOK) is None


def test_main_line_is_the_most_common_entry() -> None:
    games = [
        ucis("e4", "c6", "Nc3"),
        ucis("e4", "c6", "d4"),
        ucis("c4", "c6", "e4"),
    ]
    line = main_line(games, "Caro-Kann Defense", BOOK)
    assert [step.san for step in line.steps] == ["e4", "c6"]
    assert line.name == "Caro-Kann Defense"


def test_main_line_breaks_ties_by_length() -> None:
    games = [ucis("c4", "c6", "e4"), ucis("e4", "c6")]
    assert [s.san for s in main_line(games, "Caro-Kann Defense", BOOK).steps] == ["e4", "c6"]


def test_main_line_without_matches_is_empty() -> None:
    line = main_line([ucis("d4")], "Caro-Kann Defense", BOOK)
    assert line.name is None and line.steps == []
