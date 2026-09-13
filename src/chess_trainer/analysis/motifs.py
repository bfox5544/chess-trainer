"""Tactical motifs in an engine line, named as Lichess puzzle themes. Pure.

Used to describe a player's mistakes in the same vocabulary the Lichess
puzzle database is tagged with ("fork", "pin", "mateIn2", ...), so a mistake
can be matched to puzzles that train the same pattern.

Like `explain.py`, the detectors are conservative: a motif is reported only
when the line shows it paying off (the forked piece is taken, the pinned
piece falls). A line that wins material in some other way gets no motif
rather than a guessed one.
"""

from collections.abc import Sequence
from dataclasses import dataclass

import chess

from chess_trainer.analysis.explain import (
    MAX_LINE_PLIES,
    PIECE_VALUES,
    MoveFacts,
    explain_move,
    fork_targets,
    is_hanging,
    mate_distance_for,
    parse_line,
)

SLIDERS = (chess.BISHOP, chess.ROOK, chess.QUEEN)
# Lichess names mates up to five moves; longer ones are just "mate". Three is
# as far as a stored line reliably reaches.
NAMED_MATES = 3
# Reason codes from `explain_move` that mean a tactic was available / allowed.
MISSED_CODES = {"missed_mate", "missed_win"}
ALLOWED_CODES = {"allows_mate", "loses_material"}


def mate_theme(moves: int) -> str:
    return f"mateIn{moves}" if 1 <= moves <= NAMED_MATES else "mate"


def skewer_value(piece_type: chess.PieceType) -> int:
    """Piece value for "which piece is in front": the king outranks all."""
    return 100 if piece_type == chess.KING else PIECE_VALUES[piece_type]


def is_back_rank_mate(board: chess.Board) -> bool:
    """`board` is checkmate: is the king mated along its own back rank by a
    rook or queen, hemmed in by its own pieces?"""
    loser = board.turn
    king = board.king(loser)
    if king is None:
        return False
    rank = chess.square_rank(king)
    if rank != (0 if loser == chess.WHITE else 7):
        return False
    checkers = list(board.checkers())
    if len(checkers) != 1 or chess.square_rank(checkers[0]) != rank:
        return False
    if board.piece_type_at(checkers[0]) not in (chess.ROOK, chess.QUEEN):
        return False
    forward = rank + (1 if loser == chess.WHITE else -1)
    for file in range(chess.square_file(king) - 1, chess.square_file(king) + 2):
        if not 0 <= file <= 7:
            continue
        blocker = board.piece_at(chess.square(file, forward))
        if blocker is None or blocker.color != loser:
            return False
    return True


def takes_later(moves: Sequence[chess.Move], index: int, squares: Sequence[chess.Square]) -> bool:
    """Does the side that played moves[index] capture on one of `squares`
    with its next move?"""
    return index + 2 < len(moves) and moves[index + 2].to_square in squares


def new_pin(board: chess.Board, after: chess.Board, move: chess.Move) -> chess.Square | None:
    """The enemy piece that `move` pins to its king, if the moved piece is a
    slider that now attacks a piece which was free to move before."""
    if after.piece_type_at(move.to_square) not in SLIDERS:
        return None
    enemy = not board.turn
    for square in after.attacks(move.to_square):
        piece = after.piece_at(square)
        if piece is None or piece.color != enemy or piece.piece_type == chess.KING:
            continue
        newly_pinned = after.is_pinned(enemy, square) and not board.is_pinned(enemy, square)
        if newly_pinned and move.to_square in after.pin(enemy, square):
            return square
    return None


def is_skewer(after: chess.Board, moves: Sequence[chess.Move], index: int) -> bool:
    """moves[index] attacks a piece, it steps away, and the same slider takes
    a less valuable piece (not a pawn) that stood behind it."""
    if index + 2 >= len(moves) or after.piece_type_at(moves[index].to_square) not in SLIDERS:
        return False
    slider = moves[index].to_square
    flees, takes = moves[index + 1], moves[index + 2]
    front = after.piece_at(flees.from_square)
    behind = after.piece_at(takes.to_square)
    if front is None or behind is None or takes.from_square != slider:
        return False
    if flees.from_square not in after.attacks(slider):
        return False
    if flees.from_square not in chess.SquareSet(chess.between(slider, takes.to_square)):
        return False
    if behind.piece_type == chess.PAWN:
        return False
    return skewer_value(front.piece_type) > skewer_value(behind.piece_type)


def is_discovered_attack(board: chess.Board, moves: Sequence[chess.Move], index: int) -> bool:
    """moves[index] opened a line for another slider: onto the king, or onto
    a piece (not a pawn) that can be won or is worth more, and the line cashes
    in by taking it or by the moved piece capturing with the tempo gained."""
    move = moves[index]
    mover = board.turn
    after = board.copy(stack=False)
    after.push(move)
    follow_up = moves[index + 2] if index + 2 < len(moves) else None
    for piece_type in SLIDERS:
        for slider in after.pieces(piece_type, mover):
            if slider == move.to_square:
                continue
            opened = after.attacks(slider) & ~board.attacks(slider)
            for target in opened:
                victim = after.piece_at(target)
                if victim is None or victim.color == mover or victim.piece_type == chess.PAWN:
                    continue
                if move.from_square not in chess.SquareSet(chess.between(slider, target)):
                    continue
                if victim.piece_type == chess.KING:
                    return True
                winnable = (
                    is_hanging(after, target)
                    or PIECE_VALUES[victim.piece_type] > PIECE_VALUES[piece_type]
                )
                if winnable and follow_up is not None and cashes_in(follow_up, move, target):
                    return True
    return False


def cashes_in(follow_up: chess.Move, move: chess.Move, target: chess.Square) -> bool:
    """The move after a discovered attack takes the uncovered piece, or is
    played by the piece that stepped aside."""
    return follow_up.to_square == target or follow_up.from_square == move.to_square


def move_motifs(board: chess.Board, moves: Sequence[chess.Move], index: int) -> set[str]:
    """Motifs of moves[index], played on `board` by the side carrying out
    the tactic. Later moves of the line confirm that it pays off."""
    move = moves[index]
    found: set[str] = set()
    victim = board.piece_at(move.to_square)
    takes_piece = victim is not None and victim.piece_type != chess.PAWN
    if index == 0 and takes_piece and is_hanging(board, move.to_square):
        found.add("hangingPiece")
    if move.promotion:
        found.add("promotion")
    after = board.copy(stack=False)
    after.push(move)
    if takes_later(moves, index, fork_targets(after, move.to_square)):
        found.add("fork")
    pinned = new_pin(board, after, move)
    if pinned is not None and any(later.to_square == pinned for later in moves[index + 2 :: 2]):
        found.add("pin")
    if is_skewer(after, moves, index):
        found.add("skewer")
    if is_discovered_attack(board, moves, index):
        found.add("discoveredAttack")
    return found


def line_motifs(
    board: chess.Board, line: Sequence[chess.Move], mate_in: int | None = None
) -> set[str]:
    """Lichess themes for the tactic the side to move carries out with `line`
    (legal moves from `board`, alternating sides). `mate_in` is the engine's
    mate distance, for lines that were stored shorter than the mate."""
    attacker = board.turn
    probe = board.copy(stack=False)
    moves = list(line[:MAX_LINE_PLIES])
    found: set[str] = set()
    for index, move in enumerate(moves):
        if index % 2 == 0:
            found |= move_motifs(probe, moves, index)
        probe.push(move)
    if moves and probe.is_checkmate() and probe.turn != attacker:
        found.add(mate_theme((len(moves) + 1) // 2))
        if is_back_rank_mate(probe):
            found.add("backRankMate")
    elif mate_in is not None:
        found.add(mate_theme(mate_in))
    return found


@dataclass(frozen=True)
class MistakeMotifs:
    missed: frozenset[str]  # tactics the player had and did not play
    allowed: frozenset[str]  # tactics the move handed to the opponent


NO_MOTIFS = MistakeMotifs(frozenset(), frozenset())


def mistake_motifs(facts: MoveFacts) -> MistakeMotifs:
    """What kind of tactic a bad move missed or allowed. Relies on
    `explain_move` to decide whether there was a tactic at all (a credible
    material swing or a mate); a positional error has no motifs."""
    codes = {reason.code for reason in explain_move(facts)}
    if not codes & (MISSED_CODES | ALLOWED_CODES):
        return NO_MOTIFS
    board = chess.Board(facts.fen_before)
    mover = board.turn
    missed: set[str] = set()
    allowed: set[str] = set()
    if codes & MISSED_CODES:
        mate_in = mate_distance_for(facts.eval_before, mover) if "missed_mate" in codes else None
        missed = line_motifs(board, parse_line(board, facts.best_line), mate_in)
    if codes & ALLOWED_CODES:
        after = board.copy(stack=False)
        after.push(chess.Move.from_uci(facts.uci))
        mate_in = mate_distance_for(facts.eval_after, not mover) if "allows_mate" in codes else None
        allowed = line_motifs(after, parse_line(after, facts.reply_line), mate_in)
    return MistakeMotifs(frozenset(missed), frozenset(allowed))
