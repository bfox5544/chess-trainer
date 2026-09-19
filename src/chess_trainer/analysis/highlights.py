"""Great and brilliant moves: the good moves worth showing off.

Pure: no database and no engine. The pipeline asks the engine for a second
line where `needs_second_line` says one is worth the search, then calls
`is_great` with it.

- **Brilliant**: a sound sacrifice. After the move the opponent can win at
  least `min_sacrifice` points of material more than after the safest legal
  move (counted with a static exchange: captures on one square, cheapest
  piece first, either side may stop). Material that was lost whatever the
  mover did is not a sacrifice, nor is a piece left en prise while the move
  threatens as much in return. It is the engine's choice or within
  `max_loss` of it.
- **Great**: the only good move. The mover played the engine's first choice
  and the second best is at least `great_gap` win-probability points worse.
  Obvious only-moves are left out, because the second best is always far
  worse there: taking the piece that just moved (a recapture, or the pawn
  that attacked your queen), a capture that simply wins material, and moving
  a piece that was hanging out of the way.

Neither is awarded in book, with only one legal move, when the mover was
already winning by `max_win_pct_before` or more, or when the mover is left
below `min_win_pct_after` (an only move that keeps a lost game lost).
"""

from dataclasses import dataclass

import chess

from chess_trainer.analysis.explain import PIECE_VALUES, amount, is_hanging
from chess_trainer.db.enums import Highlight

# Bump when the rules change: games checked under an older version are
# checked again by the next analysis job.
HIGHLIGHTS_VERSION = 1


@dataclass(frozen=True)
class HighlightConfig:
    great_gap: float = 15.0  # win-% points the best move must beat the second by
    min_sacrifice: int = 2  # points of material given up (an exchange or more)
    max_loss: float = 2.0  # win-% points a brilliant move may lose to the engine's choice
    min_win_pct_after: float = 35.0  # the mover's winning chances after the move
    max_win_pct_before: float = 90.0  # already winning: nothing left to find


@dataclass(frozen=True)
class MoveSituation:
    """What the rules need to know about one move."""

    board: chess.Board  # the position before the move
    move: chess.Move
    previous: chess.Move | None  # the opponent's last move, if known
    is_best: bool
    is_forced: bool
    in_book: bool
    win_pct_before: float  # the mover's, with best play
    win_pct_after: float
    win_pct_loss: float


# --- Material ----------------------------------------------------------------


def capture_value(board: chess.Board, move: chess.Move) -> int:
    """Material a move takes, plus what a promotion adds."""
    taken = 0
    if board.is_en_passant(move):
        taken = PIECE_VALUES[chess.PAWN]
    elif (victim := board.piece_type_at(move.to_square)) is not None:
        taken = PIECE_VALUES[victim]
    if move.promotion:
        taken += PIECE_VALUES[move.promotion] - PIECE_VALUES[chess.PAWN]
    return taken


def attacker_order(board: chess.Board, move: chess.Move) -> int:
    piece = board.piece_type_at(move.from_square)
    return 100 if piece == chess.KING else PIECE_VALUES[piece or chess.PAWN]


def exchange_gain(board: chess.Board, square: chess.Square) -> int:
    """Material the side to move wins by capturing on `square`: each side
    recaptures with its cheapest piece and stops when going on would cost it."""
    captures = [
        move
        for move in board.generate_legal_captures(to_mask=chess.BB_SQUARES[square])
        if not board.is_en_passant(move)
    ]
    if not captures:
        return 0
    move = min(captures, key=lambda m: attacker_order(board, m))
    taken = capture_value(board, move)
    board.push(move)
    try:
        return max(0, taken - exchange_gain(board, square))
    finally:
        board.pop()


def best_capture_against(board: chess.Board, color: chess.Color) -> int:
    """The most material the side to move can win from `color` by one exchange."""
    targets = board.occupied_co[color] & ~board.kings
    return max((exchange_gain(board, square) for square in chess.scan_forward(targets)), default=0)


def exposed_material(board: chess.Board, move: chess.Move) -> int:
    """What the opponent can win right after `move`, less what the move took."""
    after = board.copy(stack=False)
    after.push(move)
    return best_capture_against(after, board.turn) - capture_value(board, move)


def counter_threat(after: chess.Board) -> int:
    """What the side that just moved could win next if the opponent ignored
    the position (passed). Nothing while the opponent is in check."""
    if after.is_check():
        return 0
    passed = after.copy(stack=False)
    passed.push(chess.Move.null())
    return best_capture_against(passed, after.turn)


def sacrificed_material(board: chess.Board, move: chess.Move) -> int:
    """Points the move gives up compared with the safest legal move: a knight
    put where a pawn takes it is 3. Not a sacrifice: an even trade, a piece
    that was lost whatever the mover did (say, a rook forked with check), or
    leaving a piece en prise while threatening as much in return."""
    after = board.copy(stack=False)
    after.push(move)
    if after.is_checkmate():
        return 0
    exposed = exposed_material(board, move)
    if exposed <= 0 or counter_threat(after) >= exposed:
        return 0
    # Never below zero: passing up a free capture is not a sacrifice.
    safest = max(0, min(exposed_material(board, other) for other in board.legal_moves))
    return exposed - safest


# --- Obvious moves -------------------------------------------------------------


def takes_what_just_moved(
    board: chess.Board, move: chess.Move, previous: chess.Move | None
) -> bool:
    """A recapture, or taking the piece that just attacked: the capture lands
    on (or, en passant, takes the pawn on) the opponent's last square."""
    if previous is None or not board.is_capture(move):
        return False
    if board.is_en_passant(move):
        captured = chess.square(
            chess.square_file(move.to_square), chess.square_rank(move.from_square)
        )
        return captured == previous.to_square
    return move.to_square == previous.to_square


def wins_material(board: chess.Board, move: chess.Move) -> bool:
    """A capture that comes out ahead even if the opponent recaptures."""
    if not board.is_capture(move):
        return False
    after = board.copy(stack=False)
    after.push(move)
    return capture_value(board, move) - exchange_gain(after, move.to_square) > 0


def is_obvious(situation: MoveSituation) -> bool:
    board, move = situation.board, situation.move
    return (
        takes_what_just_moved(board, move, situation.previous)
        or wins_material(board, move)
        or is_hanging(board, move.from_square)
    )


# --- Rules -------------------------------------------------------------------


def eligible(situation: MoveSituation, config: HighlightConfig) -> bool:
    return not (
        situation.is_forced
        or situation.in_book
        or situation.win_pct_before >= config.max_win_pct_before
        or situation.win_pct_after < config.min_win_pct_after
    )


def is_brilliant(situation: MoveSituation, config: HighlightConfig) -> bool:
    return (
        eligible(situation, config)
        and situation.win_pct_loss <= config.max_loss
        # The cheap check first: most moves expose nothing.
        and exposed_material(situation.board, situation.move) >= config.min_sacrifice
        and sacrificed_material(situation.board, situation.move) >= config.min_sacrifice
    )


def needs_second_line(situation: MoveSituation, config: HighlightConfig) -> bool:
    """Whether the move could be great, so the engine's second choice is
    worth searching for. Checked after `is_brilliant`."""
    return eligible(situation, config) and situation.is_best and not is_obvious(situation)


def is_great(best_win_pct: float, second_win_pct: float | None, config: HighlightConfig) -> bool:
    """`second_win_pct` is None when the engine found no second move."""
    return second_win_pct is not None and best_win_pct - second_win_pct >= config.great_gap


def highlight_text(
    highlight: Highlight,
    board: chess.Board,
    move: chess.Move,
    second_best_san: str | None,
    second_best_win_pct: float | None,
    win_pct_after: float,
) -> str:
    """One sentence on why the move earned its mark."""
    if highlight is Highlight.BRILLIANT:
        given = max(sacrificed_material(board, move), 1)
        return f"Brilliant: gives up {amount(given)}, and it is the best move."
    if second_best_san and second_best_win_pct is not None:
        return (
            f"The only good move: the next best, {second_best_san}, would have left "
            f"winning chances at {round(second_best_win_pct)}% instead of {round(win_pct_after)}%."
        )
    return "The only good move here."
