"""Move explanations on hand-built positions."""

import chess

from chess_trainer.analysis.explain import (
    MoveFacts,
    explain_move,
    fork_targets,
    move_tactics,
)
from chess_trainer.analysis.winprob import Eval
from chess_trainer.db.enums import Classification

AFTER_E4_D5 = "rnbqkbnr/ppp1pppp/8/3p4/4P3/8/PPPP1PPP/RNBQKBNR w KQkq d6 0 2"
AFTER_EXD5 = "rnbqkbnr/ppp1pppp/8/3P4/8/8/PPPP1PPP/RNBQKBNR b KQkq - 0 2"
SCHOLAR_WHITE_TO_MATE = "r1bqkb1r/pppp1ppp/2n2n2/4p2Q/2B1P3/8/PPPP1PPP/RNB1K1NR w KQkq - 4 4"
SCHOLAR_BEFORE_NF6 = "r1bqkbnr/pppp1ppp/2n5/4p2Q/2B1P3/8/PPPP1PPP/RNB1K1NR b KQkq - 3 3"


def facts(**overrides: object) -> MoveFacts:
    base: dict[str, object] = {
        "fen_before": AFTER_E4_D5,
        "uci": "e4d5",
        "classification": Classification.GOOD,
        "is_best": True,
        "eval_before": Eval(cp=30),
        "eval_after": Eval(cp=30),
        "best_line": ["e4d5", "d8d5", "b1c3"],
        "reply_line": ["d8d5", "b1c3"],
    }
    base.update(overrides)
    return MoveFacts(**base)  # type: ignore[arg-type]


def codes(reasons: list) -> list[str]:  # type: ignore[type-arg]
    return [reason.code for reason in reasons]


def test_piece_moved_onto_an_attacked_square() -> None:
    reasons = explain_move(
        facts(
            uci="f1c4",
            classification=Classification.BLUNDER,
            is_best=False,
            eval_after=Eval(cp=-300),
            reply_line=["d5c4", "g1f3"],
        )
    )
    assert codes(reasons) == ["loses_material"]
    assert reasons[0].text == (
        "Puts the bishop on c4 where it can be taken with dxc4. "
        "Black wins a piece: 2...dxc4 3. Nf3."
    )


def test_ignored_threat_is_named_as_such() -> None:
    reasons = explain_move(
        facts(
            uci="a2a3",
            classification=Classification.MISTAKE,
            is_best=False,
            eval_after=Eval(cp=-70),
            reply_line=["d5e4", "b1c3", "g8f6"],
        )
    )
    assert codes(reasons) == ["loses_material"]
    assert reasons[0].text.startswith("Ignores the threat to the pawn on e4: dxe4 wins it.")


def test_material_claims_need_the_eval_to_agree() -> None:
    """The same blunder with an eval that barely moved: counting material
    along the line says a piece, the engine says otherwise, so no claim."""
    reasons = explain_move(
        facts(
            uci="f1c4",
            classification=Classification.INACCURACY,
            is_best=False,
            eval_after=Eval(cp=-20),
            reply_line=["d5c4", "g1f3"],
        )
    )
    assert codes(reasons) == ["positional"]


def test_missed_mate() -> None:
    reasons = explain_move(
        facts(
            fen_before=SCHOLAR_WHITE_TO_MATE,
            uci="d2d3",
            classification=Classification.BLUNDER,
            is_best=False,
            eval_before=Eval(mate=1),
            eval_after=Eval(cp=50),
            best_line=["h5f7"],
            reply_line=["f6h5"],
        )
    )
    assert codes(reasons) == ["missed_mate"]
    assert reasons[0].text == "Misses a forced mate in 1: 4. Qxf7#."


def test_allowed_mate_quotes_the_line() -> None:
    reasons = explain_move(
        facts(
            fen_before=SCHOLAR_BEFORE_NF6,
            uci="g8f6",
            classification=Classification.BLUNDER,
            is_best=False,
            eval_before=Eval(cp=-30),
            eval_after=Eval(mate=1),
            best_line=["g7g6"],
            reply_line=["h5f7"],
        )
    )
    assert codes(reasons) == ["allows_mate"]
    assert reasons[0].text == "Allows White a forced mate in 1: 4. Qxf7#"


def test_delivering_mate() -> None:
    reasons = explain_move(facts(fen_before=SCHOLAR_WHITE_TO_MATE, uci="h5f7", reply_line=[]))
    assert codes(reasons) == ["checkmate"]


def test_recapture_is_not_a_material_win() -> None:
    reasons = explain_move(
        facts(
            fen_before=AFTER_EXD5,
            uci="d8d5",
            eval_before=Eval(cp=30),
            eval_after=Eval(cp=30),
            best_line=["d8d5", "b1c3", "d5a5"],
            reply_line=["b1c3", "d5a5"],
            previous_fen=AFTER_E4_D5,
            previous_uci="e4d5",
        )
    )
    assert [r.text for r in reasons] == ["Recaptures the pawn on d5."]


def test_quiet_mistake_is_called_positional() -> None:
    reasons = explain_move(
        facts(
            fen_before=chess.STARTING_FEN,
            uci="f2f3",
            classification=Classification.INACCURACY,
            is_best=False,
            eval_before=Eval(cp=30),
            eval_after=Eval(cp=-40),
            best_line=["e2e4", "e7e5"],
            reply_line=["e7e5", "e2e4"],
        )
    )
    assert codes(reasons) == ["positional"]


def test_fork_detection() -> None:
    board = chess.Board("r3k3/8/8/1N6/8/8/8/4K3 w - - 0 1")
    move = chess.Move.from_uci("b5c7")
    assert move_tactics(board, move) == ["forks the rook and the king"]
    board.push(move)
    assert fork_targets(board, chess.C7) == [chess.A8, chess.E8]


def test_illegal_move_is_not_explained() -> None:
    assert explain_move(facts(uci="e1e3")) == []
