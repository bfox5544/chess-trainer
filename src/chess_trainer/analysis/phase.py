"""Game-phase detection.

A simplified version of Lichess's "Divider", chosen because it depends only on
the position (plus a move-count cap), is cheap, and matches what players mean
by the terms:

- **Endgame**: 6 or fewer minor and major pieces left on the board in total
  (e.g. rook + minor each, or two rooks each with no minors).
- **Middlegame**: the opening is over once any of these is true:
    * 10 or fewer minor and major pieces remain (some trades have happened),
    * either side has fewer than 4 pieces left on its back rank (development
      is essentially complete),
    * 15 full moves have been played (cap for slow, closed openings).
- **Opening**: everything before that.

Phases only move forward: a game never returns to an earlier phase.
"""

import chess

from chess_trainer.db.enums import Phase

ENDGAME_MAX_PIECES = 6
MIDDLEGAME_MAX_PIECES = 10
BACKRANK_SPARSE_BELOW = 4
OPENING_MAX_PLY = 30  # 15 full moves

_ORDER = [Phase.OPENING, Phase.MIDDLEGAME, Phase.ENDGAME]


def minor_and_major_count(board: chess.Board) -> int:
    """Knights, bishops, rooks and queens of both colors."""
    return chess.popcount(board.knights | board.bishops | board.rooks | board.queens)


def backrank_is_sparse(board: chess.Board) -> bool:
    white = chess.popcount(board.occupied_co[chess.WHITE] & chess.BB_RANK_1)
    black = chess.popcount(board.occupied_co[chess.BLACK] & chess.BB_RANK_8)
    return white < BACKRANK_SPARSE_BELOW or black < BACKRANK_SPARSE_BELOW


def position_phase(board: chess.Board, ply: int) -> Phase:
    """Phase of one position, ignoring history. `ply` is 0-based."""
    pieces = minor_and_major_count(board)
    if pieces <= ENDGAME_MAX_PIECES:
        return Phase.ENDGAME
    if pieces <= MIDDLEGAME_MAX_PIECES or backrank_is_sparse(board) or ply >= OPENING_MAX_PLY:
        return Phase.MIDDLEGAME
    return Phase.OPENING


def game_phases(boards: list[chess.Board]) -> list[Phase]:
    """Phase of each position in a game, forced to be non-decreasing."""
    phases: list[Phase] = []
    current = Phase.OPENING
    for ply, board in enumerate(boards):
        current = max(current, position_phase(board, ply), key=_ORDER.index)
        phases.append(current)
    return phases


def first_ply_in(phases: list[Phase], phase: Phase) -> int | None:
    return phases.index(phase) if phase in phases else None
