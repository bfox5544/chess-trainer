"""Tactical motifs on hand-built positions."""

import chess

from chess_trainer.analysis.explain import MoveFacts
from chess_trainer.analysis.motifs import NO_MOTIFS, line_motifs, mistake_motifs
from chess_trainer.analysis.winprob import Eval
from chess_trainer.db.enums import Classification

SCHOLAR_BEFORE_NF6 = "r1bqkbnr/pppp1ppp/2n5/4p2Q/2B1P3/8/PPPP1PPP/RNB1K1NR b KQkq - 3 3"
AFTER_E4_D5 = "rnbqkbnr/ppp1pppp/8/3p4/4P3/8/PPPP1PPP/RNBQKBNR w KQkq d6 0 2"


def motifs(fen: str, line: str, mate_in: int | None = None) -> set[str]:
    return line_motifs(
        chess.Board(fen), [chess.Move.from_uci(uci) for uci in line.split()], mate_in
    )


def test_taking_an_undefended_piece_is_a_hanging_piece() -> None:
    assert motifs("4k3/8/8/4n3/8/8/8/4R1K1 w - - 0 1", "e1e5") == {"hangingPiece"}


def test_a_defended_piece_taken_by_an_equal_one_is_not_hanging() -> None:
    assert motifs("4k3/8/3p4/4n3/8/5N2/8/6K1 w - - 0 1", "f3e5 d6e5") == set()


def test_fork_needs_one_of_the_forked_pieces_to_be_taken() -> None:
    fen = "r3k3/8/8/1N6/8/8/8/6K1 w - - 0 1"
    assert motifs(fen, "b5c7 e8d7 c7a8") == {"fork"}
    assert motifs(fen, "b5c7 e8d7 c7b5") == set()


def test_pin_that_wins_the_pinned_piece() -> None:
    assert motifs("4k3/7p/2n5/8/8/8/4B3/4K3 w - - 0 1", "e2b5 h7h6 b5c6") == {"pin"}


def test_skewer_through_the_king() -> None:
    assert motifs("4q3/8/8/4k3/8/8/8/R5K1 w - - 0 1", "a1e1 e5d5 e1e8") == {"skewer"}


def test_discovered_attack_wins_the_uncovered_piece() -> None:
    found = motifs("4q1k1/8/8/8/4N3/8/8/4R1K1 w - - 0 1", "e4f6 g8g7 e1e8")
    assert "discoveredAttack" in found


def test_uncovering_an_attack_on_a_pawn_is_not_a_discovered_attack() -> None:
    assert motifs("4k3/4p3/8/8/4N3/8/8/4R1K1 w - - 0 1", "e4c5 e8d8 c5b7") == set()


def test_back_rank_mate_and_its_length() -> None:
    assert motifs("6k1/5ppp/8/8/8/8/8/R5K1 w - - 0 1", "a1a8") == {"mateIn1", "backRankMate"}


def test_mate_distance_names_a_mate_the_line_does_not_reach() -> None:
    assert motifs(AFTER_E4_D5, "", mate_in=2) == {"mateIn2"}
    assert motifs(AFTER_E4_D5, "", mate_in=5) == {"mate"}


def test_promotion() -> None:
    assert motifs("8/4P1k1/8/8/8/8/8/6K1 w - - 0 1", "e7e8q") == {"promotion"}


def test_mistake_that_allows_mate_in_one() -> None:
    found = mistake_motifs(
        MoveFacts(
            fen_before=SCHOLAR_BEFORE_NF6,
            uci="g8f6",
            classification=Classification.BLUNDER,
            is_best=False,
            eval_before=Eval(cp=20),
            eval_after=Eval(mate=1),
            best_line=["g7g6", "h5f3"],
            reply_line=["h5f7"],
        )
    )
    assert (found.missed, found.allowed) == (frozenset(), frozenset({"mateIn1"}))


def test_positional_mistake_has_no_motifs() -> None:
    found = mistake_motifs(
        MoveFacts(
            fen_before=AFTER_E4_D5,
            uci="a2a3",
            classification=Classification.INACCURACY,
            is_best=False,
            eval_before=Eval(cp=40),
            eval_after=Eval(cp=-30),
            best_line=["e4d5", "d8d5"],
            reply_line=["d5e4"],
        )
    )
    assert found == NO_MOTIFS
