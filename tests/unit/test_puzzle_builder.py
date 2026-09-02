"""Puzzle building against scripted evaluations."""

import chess
import pytest

from chess_trainer.analysis.engine import PositionEvaluation
from chess_trainer.analysis.winprob import Eval
from chess_trainer.db.enums import PuzzleOutcome
from chess_trainer.puzzles.builder import (
    PuzzleConfig,
    PuzzleDraft,
    RejectReason,
    build_puzzle,
)
from chess_trainer.puzzles.validators import PlayableLineValidator
from tests.fakes import FakeEngine, ScriptedLines, position_after, scholars_mate_script

CONFIG = PuzzleConfig()

# White mates in two on the back rank: 1.Re8+ Rxe8 2.Rxe8#.
BACK_RANK = "r5k1/5ppp/8/8/8/8/4RPPP/4R1K1 w - - 0 1"


def after(fen: str, *ucis: str) -> str:
    board = chess.Board(fen)
    for uci in ucis:
        board.push_uci(uci)
    return board.epd()


def back_rank_script() -> dict[str, ScriptedLines]:
    return {
        chess.Board(BACK_RANK).epd(): [("e2e8", Eval(mate=2)), ("h2h3", Eval(cp=20))],
        after(BACK_RANK, "e2e8"): [("a8e8", Eval(mate=1))],
        after(BACK_RANK, "e2e8", "a8e8"): [("e1e8", Eval(mate=1)), ("h2h3", Eval(cp=-400))],
    }


def build(
    board: chess.Board,
    played: str,
    script: dict[str, ScriptedLines],
    config: PuzzleConfig = CONFIG,
) -> PuzzleDraft:
    engine = FakeEngine(script)

    def evaluate(position: chess.Board, multipv: int) -> PositionEvaluation:
        return engine.analyse(position, 12, multipv)

    return build_puzzle(board, chess.Move.from_uci(played), evaluate, config)


def test_multi_move_solution_runs_to_mate() -> None:
    draft = build(chess.Board(BACK_RANK), "h2h3", back_rank_script())

    assert draft.accepted
    assert [(s.san, s.by) for s in draft.solution] == [
        ("Re8+", "user"),
        ("Rxe8", "opponent"),
        ("Rxe8#", "user"),
    ]
    assert draft.outcome is PuzzleOutcome.MATE
    first = draft.solution[0]
    assert (first.mate, first.win_pct) == (2, 100.0)
    assert first.second_best_uci == "h2h3"
    assert first.second_best_win_pct == pytest.approx(51.8, abs=0.1)
    assert draft.uniqueness_gap == pytest.approx(48.2, abs=0.1)


def test_solution_is_cut_at_max_plies_and_still_ends_on_a_user_move() -> None:
    draft = build(chess.Board(BACK_RANK), "h2h3", back_rank_script(), PuzzleConfig(max_plies=2))
    assert draft.accepted
    assert [s.san for s in draft.solution] == ["Re8+"]


def test_line_stops_when_the_next_move_is_no_longer_unique() -> None:
    """Scholar's Mate: 3...g6 is the only move, after which anything goes."""
    board = position_after("e4", "e5", "Bc4", "Nc6", "Qh5")
    draft = build(board, "g8f6", scholars_mate_script())

    assert draft.accepted
    assert [s.san for s in draft.solution] == ["g6"]
    assert draft.outcome is PuzzleOutcome.EQUALIZE  # Black is merely fine afterwards
    assert draft.uniqueness_gap == pytest.approx(24.3, abs=0.1)


def test_two_good_moves_is_not_a_puzzle() -> None:
    board = chess.Board()
    script = {board.epd(): [("e2e4", Eval(cp=300)), ("d2d4", Eval(cp=260))]}
    draft = build(board, "a2a3", script)
    assert draft.reject_reason == RejectReason.NOT_UNIQUE
    assert draft.solution == [] and draft.outcome is None
    assert draft.uniqueness_gap == pytest.approx(2.9, abs=0.1)


def test_best_move_that_still_loses_is_not_a_puzzle() -> None:
    board = chess.Board()
    script = {board.epd(): [("e2e4", Eval(cp=-250)), ("d2d4", Eval(cp=-900))]}
    assert build(board, "a2a3", script).reject_reason == RejectReason.STILL_LOST


def test_only_mating_move_is_unique_even_if_another_move_also_wins() -> None:
    board = chess.Board(BACK_RANK)
    script = back_rank_script()
    script[board.epd()] = [("e2e8", Eval(mate=2)), ("h2h3", Eval(cp=900))]
    assert build(board, "h2h3", script).accepted


def test_two_mating_moves_is_not_unique() -> None:
    board = chess.Board(BACK_RANK)
    script = {board.epd(): [("e2e8", Eval(mate=2)), ("e2e7", Eval(mate=4))]}
    assert build(board, "h2h3", script).reject_reason == RejectReason.NOT_UNIQUE


def test_deeper_search_agreeing_with_the_played_move_is_rejected() -> None:
    board = chess.Board()
    script = {board.epd(): [("e2e4", Eval(cp=300)), ("d2d4", Eval(cp=0))]}
    assert build(board, "e2e4", script).reject_reason == RejectReason.PLAYED_BEST


def test_history_sensitive_position_is_rejected() -> None:
    repeated = position_after("Nf3", "Nf6", "Ng1", "Ng8")
    assert build(repeated, "a2a3", {}).reject_reason == RejectReason.HISTORY_SENSITIVE


def test_outcome_labels_follow_the_final_win_probability() -> None:
    board = chess.Board()

    def outcome(cp: int) -> PuzzleOutcome | None:
        script = {board.epd(): [("e2e4", Eval(cp=cp)), ("d2d4", Eval(cp=-900))]}
        return build(board, "a2a3", script, PuzzleConfig(max_plies=1)).outcome

    assert outcome(30) is PuzzleOutcome.EQUALIZE  # 52.8%
    assert outcome(200) is PuzzleOutcome.ADVANTAGE  # 67.6%
    assert outcome(600) is PuzzleOutcome.CRUSHING  # 90.1%


def test_validator_rejects_illegal_and_wrong_length_lines() -> None:
    validator = PlayableLineValidator()
    board = chess.Board()
    e4, e5 = chess.Move.from_uci("e2e4"), chess.Move.from_uci("e7e5")
    assert validator.reject_reason(board, [e4]) is None
    assert validator.reject_reason(board, [e4, e5, chess.Move.from_uci("g1f3")]) is None
    assert validator.reject_reason(board, []) == "line_must_end_on_user_move"
    assert validator.reject_reason(board, [e4, e5]) == "line_must_end_on_user_move"
    assert validator.reject_reason(board, [e5]) == "illegal_move_in_line"
