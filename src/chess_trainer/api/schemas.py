"""Request and response models. Kept separate from the ORM models so the API
contract can stay stable while the schema evolves."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from chess_trainer.db.enums import (
    Classification,
    Color,
    Highlight,
    JobKind,
    JobStatus,
    Phase,
    Platform,
    PuzzleOutcome,
    TimeClass,
)


class ApiModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --- Users and accounts ------------------------------------------------------


class UserCreate(BaseModel):
    display_name: str = Field(min_length=1, max_length=100)


class AccountCreate(BaseModel):
    platform: Platform
    username: str = Field(min_length=1, max_length=100)


class AccountOut(ApiModel):
    id: int
    user_id: int
    platform: Platform
    username: str
    last_synced_at: datetime | None


class UserOut(ApiModel):
    id: int
    display_name: str
    created_at: datetime
    accounts: list[AccountOut]


# --- Jobs --------------------------------------------------------------------


class ImportRequest(BaseModel):
    time_classes: list[TimeClass] | None = Field(
        default=None, description="Only import these time classes. Omit for all."
    )
    max_games: int = Field(default=50, ge=1, le=500)
    since: datetime | None = Field(default=None, description="Only games played after this.")
    analyze: bool = Field(default=True, description="Queue analysis once the import finishes.")
    depth: int | None = Field(default=None, ge=1, le=40, description="Defaults to ANALYSIS_DEPTH.")


class AnalyzeRequest(BaseModel):
    depth: int | None = Field(default=None, ge=1, le=40, description="Defaults to ANALYSIS_DEPTH.")


class JobAccepted(BaseModel):
    job_id: int


class SyncStatusOut(BaseModel):
    interval_minutes: float | None = Field(
        description="How often linked accounts are synced; null when automatic sync is off."
    )
    active_job_id: int | None = Field(
        description="An import of this user's games whose analysis is queued or running "
        "(automatic or not), for the client to follow; null if none."
    )


class JobSummary(ApiModel):
    id: int
    kind: JobKind
    status: JobStatus
    progress_done: int
    progress_total: int | None
    result: dict[str, object] | None
    error: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class JobOut(JobSummary):
    params: dict[str, object]
    parent_id: int | None
    # e.g. the analysis job an import queued, so one poll shows the whole chain.
    children: list[JobSummary]


# --- Games and reports -------------------------------------------------------


class GameOut(ApiModel):
    id: int
    platform: Platform
    played_at: datetime | None
    white_username: str
    black_username: str
    white_rating: int | None
    black_rating: int | None
    result: str
    time_class: TimeClass
    eco: str | None
    opening_name: str | None
    opening_ply: int | None
    middlegame_start_ply: int | None
    endgame_start_ply: int | None
    analyzed_depth: int | None


class ReasonOut(ApiModel):
    code: str = Field(description="Stable identifier, e.g. loses_material, allows_mate, tactic.")
    text: str


class MoveOut(ApiModel):
    ply: int
    move_number: int
    color: Color
    san: str
    uci: str
    fen_before: str
    eval_before_cp: int | None
    eval_before_mate: int | None
    eval_after_cp: int | None
    eval_after_mate: int | None
    best_move_san: str | None
    best_move_uci: str | None
    best_line: list[str]
    win_pct_before: float
    win_pct_after: float
    win_pct_loss: float
    classification: Classification
    is_best: bool
    is_forced: bool
    in_book: bool
    phase: Phase
    clock_remaining_s: float | None
    time_spent_s: float | None
    highlight: Highlight | None = Field(
        description="Great (the only good move) or brilliant (a sound sacrifice); "
        "only linked accounts' moves are checked."
    )
    second_best_san: str | None = Field(description="Set for great moves.")
    second_best_win_pct: float | None
    explanation: list[ReasonOut] = Field(
        default_factory=list, description="Why the move was good or bad, in plain language."
    )


class HighlightedMoveOut(ApiModel):
    game: GameOut
    ply: int
    move_number: int
    color: Color
    san: str
    uci: str
    fen_before: str
    kind: Highlight
    win_pct_before: float
    win_pct_after: float
    second_best_san: str | None
    second_best_win_pct: float | None = Field(
        description="The mover's winning chances after the second best move (great moves)."
    )
    explanation: str


class HighlightsOut(ApiModel):
    great: int
    brilliant: int
    unchecked_games: int = Field(
        description="Analyzed games not yet checked for great and brilliant moves; "
        "the next analysis job checks them."
    )
    moves: list[HighlightedMoveOut] = Field(description="Newest game first.")


class StatsOut(ApiModel):
    moves: int
    inaccuracies: int
    mistakes: int
    blunders: int
    average_win_pct_loss: float
    errors_per_100_moves: float
    accuracy: float


class UserGameOut(ApiModel):
    game: GameOut
    account_id: int
    user_color: Color
    outcome: str | None
    stats: StatsOut | None


class GameReportOut(ApiModel):
    game: GameOut
    white: StatsOut
    black: StatsOut
    moves: list[MoveOut]


class BucketOut(ApiModel):
    key: str
    stats: StatsOut


class WeaknessReportOut(ApiModel):
    games_analyzed: int
    overall: StatsOut
    by_phase: list[BucketOut]
    by_opening: list[BucketOut]
    by_time_pressure: list[BucketOut]
    by_motif: dict[str, int]


class LineStepOut(ApiModel):
    uci: str
    san: str


class OpeningLineOut(ApiModel):
    name: str | None = Field(description="Opening-book name of the line's final position.")
    steps: list[LineStepOut]


class GameErrorOut(ApiModel):
    ply: int
    move_number: int
    san: str
    best_move_san: str | None
    classification: Classification
    phase: Phase
    win_pct_loss: float


class OpeningGameOut(ApiModel):
    game: GameOut
    user_color: Color
    outcome: str | None
    stats: StatsOut | None
    errors: list[GameErrorOut]


class OpeningExplorerOut(ApiModel):
    family: str
    line: OpeningLineOut
    stats: StatsOut
    games: list[OpeningGameOut]


class PlayedMoveOut(ApiModel):
    san: str
    uci: str
    count: int = Field(description="Games in which this move was played here.")


class RepeatedOccurrenceOut(ApiModel):
    game_id: int
    played_at: datetime | None
    opening_family: str | None
    ply: int
    san: str
    classification: Classification
    win_pct_loss: float


class RepeatedMistakeOut(ApiModel):
    key: str = Field(description="The position: FEN without the move counters.")
    fen: str
    color: Color
    move_number: int
    ply: int
    games: int
    best_move_san: str | None
    best_move_uci: str | None
    best_line: list[str] = Field(description="The engine's line from here (UCI), best move first.")
    worst: Classification
    average_win_pct_loss: float
    played: list[PlayedMoveOut]
    occurrences: list[RepeatedOccurrenceOut] = Field(description="One per game, newest first.")
    families: list[str]
    path: list[str] = Field(description="SAN moves leading here; empty past move 12.")
    explanation: list[ReasonOut]


# --- Puzzles -----------------------------------------------------------------


class SolutionStepOut(BaseModel):
    uci: str
    san: str
    by: str
    cp: int | None
    mate: int | None
    win_pct: float
    second_best_uci: str | None
    second_best_win_pct: float | None


class PuzzleOut(ApiModel):
    id: int
    game_id: int
    account_id: int
    ply: int
    fen: str
    user_color: Color
    phase: Phase
    severity: Classification
    outcome: PuzzleOutcome | None
    played_san: str
    played_uci: str
    played_win_pct: float
    solution: list[SolutionStepOut]
    solution_plies: int
    themes: list[str]
    depth: int


class LastMoveOut(ApiModel):
    uci: str
    san: str


class PuzzleDetailOut(PuzzleOut):
    last_move: LastMoveOut | None = Field(
        default=None,
        description="The opponent's move that led to the puzzle position; null at move one.",
    )
    explanation: list[ReasonOut] = Field(
        default_factory=list, description="Why the game move (`played_san`) was a mistake."
    )


# --- Puzzle library (Lichess puzzle database) ----------------------------------


class ThemeCountOut(ApiModel):
    theme: str
    count: int


class LibrarySummaryOut(BaseModel):
    total: int
    themes: list[ThemeCountOut]


class LibraryImportRequest(BaseModel):
    limit: int | None = Field(
        default=100_000,
        ge=1,
        description="Stop after storing this many puzzles. Null loads the whole database "
        "(about 5 million puzzles; several minutes and a few GB of disk).",
    )


class LibraryStepOut(BaseModel):
    uci: str
    san: str
    by: str


class LibraryPuzzleOut(BaseModel):
    id: str
    fen: str = Field(description="Position before the opponent's setup move.")
    setup: LibraryStepOut = Field(description="The opponent's move that sets up the puzzle.")
    start_fen: str = Field(description="Position the solver faces.")
    user_color: Color
    solution: list[LibraryStepOut]
    rating: int
    rating_deviation: int
    popularity: int
    nb_plays: int
    themes: list[str]
    game_url: str
    opening_tags: list[str]


# --- Personal training (recommended library puzzles) ---------------------------


class PuzzleRatingOut(ApiModel):
    rating: float
    deviation: float = Field(description="Glicko rating deviation: how unsure the rating is.")
    rated_attempts: int
    seeded: bool = Field(description="True until a puzzle is rated: an estimate from game ratings.")


class FocusOut(ApiModel):
    group: str = Field(description="tactic, opening, phase or level.")
    key: str
    title: str
    reason: str = Field(description="Why this is trained, in words.")
    weight: float
    theme: str | None
    opening: str | None


class TrainingProgressOut(ApiModel):
    puzzles: int = Field(description="Distinct library puzzles attempted.")
    solved: int
    first_try: int


class TrainingProfileOut(ApiModel):
    rating: PuzzleRatingOut
    foci: list[FocusOut]
    mistakes: int = Field(description="Mistakes and blunders the profile is drawn from.")
    games: int
    progress: TrainingProgressOut
    library_size: int


class RecommendationOut(BaseModel):
    puzzle: LibraryPuzzleOut
    focus: FocusOut


class LibraryAttemptIn(BaseModel):
    puzzle_id: str = Field(max_length=10)
    solved: bool = Field(description="Finished without having the solution shown.")
    first_try: bool = Field(description="Solved with no wrong move and no hint.")


class LibraryAttemptOut(ApiModel):
    rated: bool = Field(description="False for a repeat attempt at the same puzzle.")
    rating_before: float
    rating_after: float
    deviation: float


# --- Live move scoring ("keep playing") ----------------------------------------


class PositionIn(BaseModel):
    fen: str = Field(max_length=100)


class MoveScoreIn(PositionIn):
    uci: str = Field(pattern=r"^[a-h][1-8][a-h][1-8][qrbn]?$")


class EngineMoveOut(ApiModel):
    uci: str
    san: str
    fen_after: str


class EngineReplyOut(BaseModel):
    move: EngineMoveOut | None = Field(description="Null when the game is over.")


class MoveScoreOut(ApiModel):
    """The fields of an analyzed game move that exist without a game."""

    uci: str
    san: str
    color: Color
    move_number: int
    fen_before: str
    fen_after: str
    classification: Classification
    is_best: bool
    is_forced: bool
    in_book: bool
    win_pct_before: float = Field(description="The mover's winning chances before the move.")
    win_pct_after: float
    win_pct_loss: float
    eval_after_cp: int | None = Field(description="White's point of view.")
    eval_after_mate: int | None
    best_move_uci: str | None
    best_move_san: str | None
    best_line: list[str]
    explanation: list[ReasonOut]
    reply: EngineMoveOut | None = Field(
        description="The engine's answer, so play can continue; null when the game is over."
    )
