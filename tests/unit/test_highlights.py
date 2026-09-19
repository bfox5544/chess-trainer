import chess
import pytest

from chess_trainer.analysis.highlights import (
    HighlightConfig,
    MoveSituation,
    exchange_gain,
    highlight_text,
    is_brilliant,
    is_great,
    needs_second_line,
    sacrificed_material,
    takes_what_just_moved,
)
from chess_trainer.db.enums import Highlight

CONFIG = HighlightConfig()
# 3.Ng5 puts the knight where the h6 pawn takes it.
KNIGHT_SAC = "rnbqkb1r/ppppppp1/5n1p/8/8/5N2/PPPPPPPP/RNBQKB1R w KQkq - 0 3"


def situation(fen: str, uci: str, **overrides: object) -> MoveSituation:
    values: dict[str, object] = {
        "board": chess.Board(fen),
        "move": chess.Move.from_uci(uci),
        "previous": None,
        "is_best": True,
        "is_forced": False,
        "in_book": False,
        "win_pct_before": 55.0,
        "win_pct_after": 55.0,
        "win_pct_loss": 0.0,
    }
    values.update(overrides)
    return MoveSituation(**values)  # type: ignore[arg-type]


def sacrifice(fen: str, uci: str) -> int:
    return sacrificed_material(chess.Board(fen), chess.Move.from_uci(uci))


def test_exchange_gain_stops_when_going_on_would_cost() -> None:
    pawn_takes_pawn = chess.Board("4k3/8/8/3p4/4P3/8/8/4K3 w - - 0 1")
    assert exchange_gain(pawn_takes_pawn, chess.D5) == 1
    # Qxd5 would win a pawn and lose the queen to ...exd5: White does not take.
    defended = chess.Board("4k3/8/4p3/3p4/8/8/8/3QK3 w - - 0 1")
    assert exchange_gain(defended, chess.D5) == 0


@pytest.mark.parametrize(
    ("fen", "uci", "points"),
    [
        pytest.param(KNIGHT_SAC, "f3g5", 3, id="knight left to a pawn"),
        pytest.param(
            "r1bqkbnr/pppp1ppp/2n5/1B2p3/4P3/5N2/PPPP1PPP/RNBQK2R w KQkq - 2 4",
            "b5c6",
            0,
            id="even trade",
        ),
        pytest.param(
            "r3k3/2N5/8/8/8/8/8/4K3 b - - 0 1", "e8d7", 0, id="rook lost to a fork anyway"
        ),
        pytest.param(
            "r1b2rk1/ppNp1pp1/2n3qp/2b1p3/2B1P3/3P1N2/PPP2PPP/R2QK2R b KQ - 0 9",
            "g6g2",
            0,
            id="rook left en prise while attacking a rook",
        ),
        pytest.param("6k1/5ppp/8/8/8/8/5PPP/3R2K1 w - - 0 1", "d1d8", 0, id="checkmate"),
    ],
)
def test_sacrificed_material(fen: str, uci: str, points: int) -> None:
    assert sacrifice(fen, uci) == points


def test_brilliant_needs_a_sound_sacrifice_in_an_open_game() -> None:
    assert is_brilliant(situation(KNIGHT_SAC, "f3g5"), CONFIG)
    assert not is_brilliant(situation(KNIGHT_SAC, "f3g5", win_pct_loss=8.0), CONFIG)
    assert not is_brilliant(situation(KNIGHT_SAC, "f3g5", win_pct_before=95.0), CONFIG)
    assert not is_brilliant(situation(KNIGHT_SAC, "f3g5", win_pct_after=20.0), CONFIG)
    assert not is_brilliant(situation(KNIGHT_SAC, "f3g5", in_book=True), CONFIG)
    assert not is_brilliant(situation(KNIGHT_SAC, "b1c3"), CONFIG)  # gives nothing up


def test_taking_what_just_moved_counts_en_passant() -> None:
    board = chess.Board()
    for san in ["e4", "a6", "e5", "d5"]:
        board.push_san(san)
    d7d5 = chess.Move.from_uci("d7d5")
    assert takes_what_just_moved(board, chess.Move.from_uci("e5d6"), d7d5)
    assert not takes_what_just_moved(board, chess.Move.from_uci("g1f3"), d7d5)


def test_obvious_moves_are_not_searched_for_great() -> None:
    # The b4 knight is attacked by the a3 pawn: retreating it is no find.
    retreat = "r1bqk2r/pppp1ppp/1b3n2/3P4/1n2P3/P4P2/1P2N1PP/RNBQKB1R b KQkq - 0 8"
    assert not needs_second_line(situation(retreat, "b4a6"), CONFIG)
    # A recapture.
    after_trade = "r1bqkbnr/pppp1ppp/2B5/4p3/4P3/5N2/PPPP1PPP/RNBQK2R b KQkq - 0 4"
    recapture = situation(after_trade, "d7c6", previous=chess.Move.from_uci("b5c6"))
    assert not needs_second_line(recapture, CONFIG)
    # A quiet move is a candidate; not the engine's choice, or forced, is not.
    assert needs_second_line(situation(chess.STARTING_FEN, "g1f3"), CONFIG)
    assert not needs_second_line(situation(chess.STARTING_FEN, "g1f3", is_best=False), CONFIG)
    assert not needs_second_line(situation(chess.STARTING_FEN, "g1f3", is_forced=True), CONFIG)


def test_great_needs_the_second_best_to_be_much_worse() -> None:
    assert is_great(60.0, 40.0, CONFIG)
    assert not is_great(60.0, 50.0, CONFIG)
    assert not is_great(60.0, None, CONFIG)


def test_highlight_text() -> None:
    board, move = chess.Board(KNIGHT_SAC), chess.Move.from_uci("f3g5")
    brilliant = highlight_text(Highlight.BRILLIANT, board, move, None, None, 55.0)
    assert brilliant == "Brilliant: gives up a piece, and it is the best move."
    great = highlight_text(Highlight.GREAT, board, move, "Nc3", 31.6, 54.6)
    assert great == (
        "The only good move: the next best, Nc3, would have left winning chances "
        "at 32% instead of 55%."
    )
