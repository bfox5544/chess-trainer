"""Final checks a generated solution must pass before a puzzle is accepted.

This is the slot for stricter rules later (material actually won, a motif is
present, ...): add a class with `name` and `reject_reason`, append it to
`VALIDATORS`.
"""

from collections.abc import Sequence
from typing import Protocol

import chess


class PuzzleValidator(Protocol):
    name: str

    def reject_reason(self, board: chess.Board, solution: Sequence[chess.Move]) -> str | None:
        """None if the solution is acceptable, otherwise a short reason code."""
        ...


class PlayableLineValidator:
    """The line is legal from the start position and ends on the solver's move."""

    name = "playable_line"

    def reject_reason(self, board: chess.Board, solution: Sequence[chess.Move]) -> str | None:
        if len(solution) % 2 == 0:  # also catches an empty line
            return "line_must_end_on_user_move"
        position = board.copy(stack=False)
        for move in solution:
            if move not in position.legal_moves:
                return "illegal_move_in_line"
            position.push(move)
        return None


VALIDATORS: list[PuzzleValidator] = [PlayableLineValidator()]


def first_rejection(board: chess.Board, solution: Sequence[chess.Move]) -> str | None:
    for validator in VALIDATORS:
        reason = validator.reject_reason(board, solution)
        if reason is not None:
            return reason
    return None
