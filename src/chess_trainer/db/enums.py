"""Enumerations shared by the models and the domain logic."""

from enum import StrEnum


class Platform(StrEnum):
    LICHESS = "lichess"
    CHESSCOM = "chesscom"


class TimeClass(StrEnum):
    BULLET = "bullet"
    BLITZ = "blitz"
    RAPID = "rapid"
    CLASSICAL = "classical"
    CORRESPONDENCE = "correspondence"


class Color(StrEnum):
    WHITE = "white"
    BLACK = "black"


class Classification(StrEnum):
    GOOD = "good"  # best move or within the inaccuracy threshold
    INACCURACY = "inaccuracy"
    MISTAKE = "mistake"
    BLUNDER = "blunder"


class Highlight(StrEnum):
    """A good move worth showing off (see analysis/highlights.py)."""

    GREAT = "great"  # the only good move
    BRILLIANT = "brilliant"  # a sound sacrifice


class Phase(StrEnum):
    OPENING = "opening"
    MIDDLEGAME = "middlegame"
    ENDGAME = "endgame"


class JobKind(StrEnum):
    IMPORT = "import"
    ANALYZE = "analyze"
    PUZZLE_LIBRARY = "puzzle_library"  # load the Lichess puzzle database


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class PuzzleStatus(StrEnum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class PuzzleOutcome(StrEnum):
    MATE = "mate"
    CRUSHING = "crushing"
    ADVANTAGE = "advantage"
    EQUALIZE = "equalize"


class PuzzleSource(StrEnum):
    OWN_GAME = "own_game"
