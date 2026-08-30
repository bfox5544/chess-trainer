from collections.abc import Callable

import chess
import pytest

from chess_trainer.analysis.phase import (
    backrank_is_sparse,
    first_ply_in,
    game_phases,
    minor_and_major_count,
    position_phase,
)
from chess_trainer.analysis.replay import replay_pgn
from chess_trainer.db.enums import Phase

# Italian Game, both sides castled, all 14 minor/major pieces still on.
DEVELOPING = "r1bq1rk1/pppp1ppp/2n2n2/2b1p3/2B1P3/2NP1N2/PPP2PPP/R1BQ1RK1 w - - 0 7"
# Same structure with White fully developed: only R, R, K left on rank 1.
DEVELOPED = "r2q1rk1/ppp2ppp/2npbn2/2b1p3/2B1P3/2NPBN2/PPPQ1PPP/R4RK1 b - - 0 9"
# Queens and one minor pair traded: 10 minor/major pieces, back ranks still full.
TRADED = "rnb1kb1r/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNB1KB1R w KQkq - 0 8"
SEVEN_PIECES = "2r2rk1/5ppp/2n5/8/8/2N1B3/5PPP/2RR2K1 w - - 0 25"
SIX_PIECES = "2r2rk1/5ppp/2n5/8/8/2N5/5PPP/2RR2K1 w - - 0 25"
ROOK_ENDGAME = "8/5pk1/6p1/8/8/6P1/r4PK1/1R6 w - - 0 40"
PAWN_ENDGAME = "8/5pk1/6p1/8/8/6P1/5PK1/8 w - - 0 50"


def phase_of(fen: str, ply: int = 10) -> Phase:
    return position_phase(chess.Board(fen), ply)


def test_start_position_is_opening() -> None:
    assert position_phase(chess.Board(), 0) is Phase.OPENING


def test_still_developing_is_opening() -> None:
    board = chess.Board(DEVELOPING)
    assert minor_and_major_count(board) == 14
    assert not backrank_is_sparse(board)
    assert position_phase(board, 12) is Phase.OPENING


def test_completed_development_starts_the_middlegame() -> None:
    assert backrank_is_sparse(chess.Board(DEVELOPED))
    assert phase_of(DEVELOPED) is Phase.MIDDLEGAME


def test_early_trades_start_the_middlegame() -> None:
    board = chess.Board(TRADED)
    assert minor_and_major_count(board) == 10
    assert not backrank_is_sparse(board)
    assert position_phase(board, 14) is Phase.MIDDLEGAME


def test_move_fifteen_caps_the_opening() -> None:
    assert position_phase(chess.Board(), 29) is Phase.OPENING
    assert position_phase(chess.Board(), 30) is Phase.MIDDLEGAME


@pytest.mark.parametrize(
    ("fen", "expected"),
    [
        (SEVEN_PIECES, Phase.MIDDLEGAME),
        (SIX_PIECES, Phase.ENDGAME),
        (ROOK_ENDGAME, Phase.ENDGAME),
        (PAWN_ENDGAME, Phase.ENDGAME),
    ],
)
def test_endgame_boundary_is_six_pieces(fen: str, expected: Phase) -> None:
    assert phase_of(fen, ply=50) is expected


def test_phases_never_go_backwards() -> None:
    boards = [chess.Board(), chess.Board(ROOK_ENDGAME), chess.Board(DEVELOPED), chess.Board()]
    assert game_phases(boards) == [Phase.OPENING, Phase.ENDGAME, Phase.ENDGAME, Phase.ENDGAME]


def test_opera_game_phases(load_pgn: Callable[[str], str]) -> None:
    phases = game_phases(replay_pgn(load_pgn("chesscom_opera_game")).boards)
    # 9.Bg5 empties White's back rank down to R, K, R: development is done.
    assert first_ply_in(phases, Phase.MIDDLEGAME) == 17
    # After 16...Nxb8 only six pieces remain, just before 17.Rd8#.
    assert first_ply_in(phases, Phase.ENDGAME) == 32


def test_short_game_never_leaves_the_opening(load_pgn: Callable[[str], str]) -> None:
    phases = game_phases(replay_pgn(load_pgn("lichess_scholars_mate")).boards)
    assert set(phases) == {Phase.OPENING}
    assert first_ply_in(phases, Phase.ENDGAME) is None
