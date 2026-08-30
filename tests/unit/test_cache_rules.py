"""The pure rules behind the evaluation cache (no database)."""

import chess

from chess_trainer.analysis.cache import is_history_sensitive, position_key, terminal_evaluation
from chess_trainer.analysis.engine import fingerprint
from chess_trainer.analysis.winprob import Eval
from tests.fakes import position_after


def test_key_ignores_move_order_and_counters() -> None:
    one = position_after("e4", "e5", "Nf3", "Nc6")
    two = position_after("Nf3", "Nc6", "e4", "e5")
    assert one.fen() != two.fen()  # halfmove clocks differ
    assert position_key(one) == position_key(two)


def test_key_distinguishes_side_to_move_and_castling_rights() -> None:
    white_to_move = chess.Board("4k3/8/8/8/8/8/8/R3K3 w Q - 0 1")
    black_to_move = chess.Board("4k3/8/8/8/8/8/8/R3K3 b Q - 0 1")
    no_castling = chess.Board("4k3/8/8/8/8/8/8/R3K3 w - - 0 1")
    assert len({position_key(b) for b in (white_to_move, black_to_move, no_castling)}) == 3


def test_ordinary_position_is_not_history_sensitive() -> None:
    assert not is_history_sensitive(position_after("e4", "e5"))


def test_repeated_position_is_history_sensitive() -> None:
    board = position_after("Nf3", "Nf6", "Ng1", "Ng8")  # start position again
    assert is_history_sensitive(board)
    # The same position without its history is fine: that's what gets cached.
    assert not is_history_sensitive(board.copy(stack=False))


def test_high_halfmove_clock_is_history_sensitive() -> None:
    assert not is_history_sensitive(chess.Board("8/8/4k3/8/8/4K3/8/R7 w - - 79 90"))
    assert is_history_sensitive(chess.Board("8/8/4k3/8/8/4K3/8/R7 w - - 80 90"))


def test_checkmate_is_scored_from_the_rules() -> None:
    mated = position_after("e4", "e5", "Bc4", "Nc6", "Qh5", "Nf6", "Qxf7#")
    evaluation = terminal_evaluation(mated, depth=12)
    assert evaluation is not None
    assert evaluation.best.eval == Eval.checkmate(chess.WHITE)
    assert evaluation.best.pv == ()


def test_stalemate_is_a_draw_and_live_positions_are_not_terminal() -> None:
    stalemate = chess.Board("7k/5Q2/6K1/8/8/8/8/8 b - - 0 1")
    evaluation = terminal_evaluation(stalemate, depth=12)
    assert evaluation is not None and evaluation.best.eval == Eval.draw()
    assert terminal_evaluation(chess.Board(), depth=12) is None


def test_fingerprint_covers_version_and_eval_options_only() -> None:
    base = fingerprint("Stockfish 17", {})
    assert base == fingerprint("Stockfish 17", {})
    assert base != fingerprint("Stockfish 16", {})
    assert base != fingerprint("Stockfish 17", {"EvalFile": "custom.nnue"})
    # Option order must not matter.
    assert fingerprint("X", {"a": "1", "b": "2"}) == fingerprint("X", {"b": "2", "a": "1"})
