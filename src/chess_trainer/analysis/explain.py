"""Plain-language reasons why a move was good or bad.

Pure: works only from data the analysis already stored, so explanations are
built at read time and every previously analyzed game gets them for free.

Inputs per move:
- the position before it and the move played,
- the engine's best line from that position (what should have happened),
- the engine's best line from the position *after* it, which is the next
  ply's `best_line` (how the opponent punishes it),
- the evals before and after.

The heuristics are deliberately conservative. Each reason is a concrete,
checkable claim (a capture, a fork, a mate, a net material swing along an
engine line). When none applies, a bad move is described as positional
rather than inventing a tactic.

Material is counted in the usual units (P=1, N=B=3, R=5, Q=9) and only at a
"quiet" point of a line: no side in check and the next move neither captures
nor checks. Counting mid-exchange would report a queen lost when it is
about to be recaptured.
"""

from collections.abc import Sequence
from dataclasses import dataclass

import chess

from chess_trainer.analysis.winprob import Eval
from chess_trainer.db.enums import Classification

PIECE_VALUES = {
    chess.PAWN: 1,
    chess.KNIGHT: 3,
    chess.BISHOP: 3,
    chess.ROOK: 5,
    chess.QUEEN: 9,
    chess.KING: 0,
}
# How far along an engine line material is followed. Long enough for a
# fork-then-capture (4 plies) plus a recapture; short enough that unrelated
# later gains in the line are not credited to this move.
MAX_LINE_PLIES = 8
# Moves shown when quoting a line in a reason.
QUOTE_PLIES = 4
# A material claim of N points needs the eval to have moved by at least
# N * CP_PER_POINT centipawns (a pawn is ~100; positional compensation and
# search noise leave room).
CP_PER_POINT = 60
MATE_AS_CP = 10_000
ERRORS = (Classification.INACCURACY, Classification.MISTAKE, Classification.BLUNDER)


@dataclass(frozen=True)
class Reason:
    code: str  # stable identifier for clients, e.g. "hangs_piece"
    text: str


@dataclass(frozen=True)
class MoveFacts:
    fen_before: str
    uci: str
    classification: Classification
    is_best: bool
    eval_before: Eval
    eval_after: Eval
    best_line: Sequence[str]  # from fen_before; best_line[0] is the best move
    reply_line: Sequence[str]  # from the position after the move; may be empty
    previous_fen: str | None = None  # the position before the opponent's last move
    previous_uci: str | None = None


# --- Small board helpers -----------------------------------------------------


def material(board: chess.Board, color: chess.Color) -> int:
    """Material balance from `color`'s point of view."""
    total = 0
    for piece in board.piece_map().values():
        value = PIECE_VALUES[piece.piece_type]
        total += value if piece.color == color else -value
    return total


def piece_name(piece_type: chess.PieceType) -> str:
    return chess.piece_name(piece_type)


def side_name(color: chess.Color) -> str:
    return "White" if color == chess.WHITE else "Black"


def amount(points: int) -> str:
    """A material swing in words."""
    named = {1: "a pawn", 2: "two pawns", 3: "a piece", 4: "a piece and a pawn", 5: "a rook"}
    if points in named:
        return named[points]
    if points == 9:
        return "a queen"
    return f"material worth {points} pawns"


def parse_line(board: chess.Board, ucis: Sequence[str]) -> list[chess.Move]:
    """The legal prefix of a UCI line from `board`."""
    moves: list[chess.Move] = []
    probe = board.copy(stack=False)
    for uci in ucis:
        try:
            move = chess.Move.from_uci(uci)
        except ValueError:
            break
        if move not in probe.legal_moves:
            break
        moves.append(move)
        probe.push(move)
    return moves


def line_san(board: chess.Board, moves: Sequence[chess.Move], limit: int = QUOTE_PLIES) -> str:
    """Moves as SAN with move numbers, e.g. '12...Nxe5 13. dxe5 Qxd1'."""
    probe = board.copy(stack=False)
    parts: list[str] = []
    for index, move in enumerate(moves[:limit]):
        number = probe.fullmove_number
        if probe.turn == chess.WHITE:
            parts.append(f"{number}. {probe.san(move)}")
        else:
            prefix = f"{number}..." if index == 0 else ""
            parts.append(f"{prefix}{probe.san(move)}")
        probe.push(move)
    return " ".join(parts)


def is_quiet(board: chess.Board, next_move: chess.Move | None) -> bool:
    if board.is_check():
        return False
    if next_move is None:
        return True
    return not board.is_capture(next_move) and not board.gives_check(next_move)


def settled_material(
    board: chess.Board, moves: Sequence[chess.Move], color: chess.Color, min_plies: int
) -> int:
    """Material for `color` at the first quiet point at or after `min_plies`
    moves into the line (or at the end of what was followed)."""
    probe = board.copy(stack=False)
    moves = list(moves[:MAX_LINE_PLIES])
    for index in range(len(moves) + 1):
        next_move = moves[index] if index < len(moves) else None
        if index >= min_plies and is_quiet(probe, next_move):
            return material(probe, color)
        if next_move is None:
            break
        probe.push(next_move)
    return material(probe, color)


def is_hanging(board: chess.Board, square: chess.Square) -> bool:
    """Can the piece on `square` be won: attacked and either undefended or
    attacked by something cheaper?"""
    piece = board.piece_at(square)
    if piece is None or piece.piece_type == chess.KING:
        return False
    attackers = board.attackers(not piece.color, square)
    if not attackers:
        return False
    if not board.attackers(piece.color, square):
        return True
    cheapest = min(PIECE_VALUES[board.piece_type_at(s) or chess.PAWN] for s in attackers)
    return cheapest < PIECE_VALUES[piece.piece_type]


def fork_targets(board: chess.Board, square: chess.Square) -> list[chess.Square]:
    """Enemy pieces the piece on `square` attacks that it could profitably
    take: the king, anything worth more, or anything undefended. A fork is
    two or more of these at once."""
    attacker = board.piece_at(square)
    if attacker is None:
        return []
    targets = []
    for target in board.attacks(square):
        victim = board.piece_at(target)
        if victim is None or victim.color == attacker.color:
            continue
        defended = bool(board.attackers(victim.color, target))
        if (
            victim.piece_type == chess.KING
            or PIECE_VALUES[victim.piece_type] > PIECE_VALUES[attacker.piece_type]
            or (not defended and victim.piece_type != chess.PAWN)
        ):
            targets.append(target)
    return targets if len(targets) >= 2 else []


def describe_targets(board: chess.Board, squares: Sequence[chess.Square]) -> str:
    names = []
    for square in squares:
        piece = board.piece_at(square)
        if piece is not None:
            names.append(f"the {piece_name(piece.piece_type)}")
    if len(names) <= 2:
        return " and ".join(names)
    return ", ".join(names[:-1]) + f" and {names[-1]}"


def mate_distance_for(evaluation: Eval, color: chess.Color) -> int | None:
    """Moves until `color` mates, if it has a forced mate."""
    if evaluation.mate is None:
        return None
    sign = 1 if color == chess.WHITE else -1
    return evaluation.mate * sign if evaluation.mate * sign > 0 else None


def mover_cp(evaluation: Eval, color: chess.Color) -> int:
    """Centipawns from `color`'s point of view; mates count as a huge score."""
    sign = 1 if color == chess.WHITE else -1
    if evaluation.mate is not None:
        return sign * (MATE_AS_CP if evaluation.mate > 0 else -MATE_AS_CP)
    return sign * max(-MATE_AS_CP, min(MATE_AS_CP, evaluation.cp or 0))


def credible(points: int, cp_swing: int) -> bool:
    """Does the engine's score back up a material claim? Counting material
    along a line can stop mid-trade (a pawn taken now, won back three moves
    later); the eval cannot be fooled that way."""
    return cp_swing >= CP_PER_POINT * points


# --- What a single move does -------------------------------------------------


def move_tactics(
    board: chess.Board, move: chess.Move, recapture_square: chess.Square | None = None
) -> list[str]:
    """Short phrases for what `move` does on `board`: a profitable capture,
    a fork, a promotion. Empty for a quiet move. Taking back on
    `recapture_square` (where the opponent just captured) is a recapture,
    never "winning" a piece that only just landed there."""
    phrases: list[str] = []
    captured = board.piece_at(move.to_square)
    if board.is_en_passant(move):
        captured = chess.Piece(chess.PAWN, not board.turn)
    after = board.copy(stack=False)
    after.push(move)
    if captured is not None:
        mover_type = board.piece_type_at(move.from_square) or chess.PAWN
        undefended = not board.attackers(captured.color, move.to_square)
        square = chess.square_name(move.to_square)
        if move.to_square == recapture_square:
            phrases.append(f"recaptures the {piece_name(captured.piece_type)} on {square}")
        elif undefended and captured.piece_type != chess.PAWN:
            phrases.append(f"takes the undefended {piece_name(captured.piece_type)} on {square}")
        elif PIECE_VALUES[captured.piece_type] > PIECE_VALUES[mover_type]:
            phrases.append(
                f"wins the {piece_name(captured.piece_type)} on {square} for a "
                f"{piece_name(mover_type)}"
            )
    if move.promotion:
        phrases.append(f"promotes to a {piece_name(move.promotion)}")
    targets = fork_targets(after, move.to_square)
    if targets:
        phrases.append(f"forks {describe_targets(after, targets)}")
    return phrases


def join_phrases(phrases: Sequence[str]) -> str:
    return phrases[0] if len(phrases) == 1 else ", ".join(phrases[:-1]) + " and " + phrases[-1]


# --- Explanations -------------------------------------------------------------


def last_capture_square(facts: MoveFacts) -> chess.Square | None:
    """Where the opponent's previous move captured, if it did."""
    if not (facts.previous_fen and facts.previous_uci):
        return None
    try:
        last = chess.Move.from_uci(facts.previous_uci)
    except ValueError:
        return None
    return last.to_square if chess.Board(facts.previous_fen).is_capture(last) else None


def baseline_material(
    facts: MoveFacts, board: chess.Board, candidates: Sequence[chess.Move]
) -> int:
    """Material before this move. If the opponent just captured and one of
    `candidates` (the played or the best move) takes back on that square, an
    exchange is in progress: count from before the opponent's capture, so a
    recapture restores balance instead of "winning" a piece. A capture that
    cannot be answered on the same square is left as already lost."""
    mover = board.turn
    square = last_capture_square(facts)
    recaptures = any(move.to_square == square and board.is_capture(move) for move in candidates)
    if square is not None and recaptures and facts.previous_fen:
        return material(chess.Board(facts.previous_fen), mover)
    return material(board, mover)


def explain_move(facts: MoveFacts) -> list[Reason]:
    board = chess.Board(facts.fen_before)
    mover = board.turn
    played = chess.Move.from_uci(facts.uci)
    if played not in board.legal_moves:
        return []
    after = board.copy(stack=False)
    after.push(played)
    if after.is_checkmate():
        return [Reason("checkmate", "Checkmate.")]

    reply = parse_line(after, facts.reply_line)
    best = parse_line(board, facts.best_line)
    baseline = baseline_material(facts, board, [played, *best[:1]])
    played_net = settled_material(board, [played, *reply], mover, min_plies=2) - baseline
    best_net = settled_material(board, best, mover, min_plies=2) - baseline if best else played_net

    if facts.classification in ERRORS:
        return explain_error(facts, board, after, played, reply, best, played_net, best_net)
    return explain_good(facts, board, played, played_net)


def explain_good(
    facts: MoveFacts, board: chess.Board, played: chess.Move, played_net: int
) -> list[Reason]:
    mover = board.turn
    reasons: list[Reason] = []
    mate_in = mate_distance_for(facts.eval_after, mover)
    if mate_in is not None:
        reasons.append(Reason("forced_mate", f"Starts a forced mate in {mate_in}."))
    tactics = move_tactics(board, played, last_capture_square(facts))
    if tactics:
        text = join_phrases(tactics)
        reasons.append(Reason("tactic", text[0].upper() + text[1:] + "."))
    gained = mover_cp(facts.eval_after, mover)
    if played_net >= 1 and mate_in is None and credible(played_net, gained):
        reasons.append(
            Reason(
                "wins_material",
                f"With best play {side_name(mover)} wins {amount(played_net)}.",
            )
        )
    return reasons


def explain_error(
    facts: MoveFacts,
    board: chess.Board,
    after: chess.Board,
    played: chess.Move,
    reply: Sequence[chess.Move],
    best: Sequence[chess.Move],
    played_net: int,
    best_net: int,
) -> list[Reason]:
    mover = board.turn
    opponent = side_name(not mover)
    reasons: list[Reason] = []

    # Mates outrank material: name them first and stop there.
    allowed = mate_distance_for(facts.eval_after, not mover)
    if allowed is not None:
        line = f": {line_san(after, reply, limit=allowed * 2 - 1)}" if reply else "."
        reasons.append(Reason("allows_mate", f"Allows {opponent} a forced mate in {allowed}{line}"))
    missed = mate_distance_for(facts.eval_before, mover)
    if missed is not None and mate_distance_for(facts.eval_after, mover) is None and best:
        reasons.append(
            Reason("missed_mate", f"Misses a forced mate in {missed}: {line_san(board, best)}.")
        )
    if reasons:
        return reasons

    # Two separate questions: did the move lose material it had, and did it
    # pass up material it could have won? Both can be true at once.
    worse_than_best = best_net - played_net >= 1
    cost = mover_cp(facts.eval_before, mover) - mover_cp(facts.eval_after, mover)
    if played_net <= -1 and worse_than_best and reply and credible(-played_net, cost):
        lost = -played_net
        reasons.append(Reason("loses_material", punishment(board, after, played, reply, lost)))
    if best_net >= 1 and worse_than_best and best and credible(best_net, cost):
        reasons.append(
            Reason("missed_win", missed_win(board, best, best_net, last_capture_square(facts)))
        )

    if not reasons:
        reasons.append(
            Reason(
                "positional",
                "No tactic wins material right away; the engine simply rates the "
                "position worse afterwards (piece activity, pawn structure or king safety).",
            )
        )
    return reasons


def punishment(
    board: chess.Board,
    after: chess.Board,
    played: chess.Move,
    reply: Sequence[chess.Move],
    lost: int,
) -> str:
    """How the opponent wins material after the played move."""
    mover = board.turn
    opponent = side_name(not mover)
    answer = reply[0]
    answer_san = after.san(answer)
    swing = f"{opponent} wins {amount(lost)}: {line_san(after, reply)}."

    # Only call a piece lost when it really is (undefended, or attacked by
    # something cheaper); a capture that starts an even trade is described
    # by the line and the net result instead.
    if after.is_capture(answer) and is_hanging(after, answer.to_square):
        square = answer.to_square
        victim = after.piece_at(square)
        name = piece_name(victim.piece_type) if victim else "pawn"
        where = f"the {name} on {chess.square_name(square)}"
        if square == played.to_square:
            return f"Puts {where} where it can be taken with {answer_san}. {swing}"
        if threat_existed(board, answer):
            return f"Ignores the threat to {where}: {answer_san} wins it. {swing}"
        if board.piece_type_at(played.from_square) is not None and square in board.attacks(
            played.from_square
        ):
            return f"Stops defending {where}, so {answer_san} wins it. {swing}"
        return f"Leaves {where} exposed to {answer_san}. {swing}"
    if after.is_capture(answer):
        return f"Allows {answer_san}, and the exchanges that follow cost material. {swing}"

    probe = after.copy(stack=False)
    probe.push(answer)
    targets = fork_targets(probe, answer.to_square)
    if targets:
        return f"Allows {answer_san}, forking {describe_targets(probe, targets)}. {swing}"
    if probe.is_check():
        return f"Allows {answer_san} with check, and material falls. {swing}"
    return f"After the reply {answer_san}, material can't be held. {swing}"


def threat_existed(board: chess.Board, answer: chess.Move) -> bool:
    """Was the opponent's winning capture already on the board before this
    move, i.e. did the move ignore it rather than create it?"""
    if board.is_check():
        return False
    probe = board.copy(stack=False)
    probe.push(chess.Move.null())
    return answer in probe.legal_moves and is_hanging(probe, answer.to_square)


def missed_win(
    board: chess.Board,
    best: Sequence[chess.Move],
    best_net: int,
    recapture_square: chess.Square | None,
) -> str:
    first = best[0]
    tactics = move_tactics(board, first, recapture_square)
    how = f" ({join_phrases(tactics)})" if tactics else ""
    return f"Misses {board.san(first)}{how}, winning {amount(best_net)}: {line_san(board, best)}."
