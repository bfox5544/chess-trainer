"""Application settings, loaded from environment variables (and `.env`).

Every tunable lives here so thresholds are never hard-coded in logic modules.
Pure functions receive small frozen dataclasses built from these settings,
which keeps them testable without touching the environment.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Database
    database_url: str = "postgresql+psycopg://chess:chess@localhost:54329/chess_trainer"
    test_database_url: str = "postgresql+psycopg://chess:chess@localhost:54329/chess_trainer_test"

    # Stockfish
    stockfish_path: str = "/opt/homebrew/bin/stockfish"
    engine_threads: int = 2
    engine_hash_mb: int = 128
    engine_eval_file: str | None = None
    analysis_depth: int = 16
    puzzle_depth: int | None = None

    # Move classification: win-probability points lost (0-100 scale).
    inaccuracy_threshold: float = 5.0
    mistake_threshold: float = 10.0
    blunder_threshold: float = 15.0

    # Time pressure: clock below min(seconds, fraction * base time).
    time_pressure_seconds: float = 30.0
    time_pressure_fraction: float = 0.1

    # Puzzle generation
    puzzle_uniqueness_gap: float = 15.0
    puzzle_min_result_win_pct: float = 50.0
    puzzle_max_plies: int = 10
    puzzle_crushing_win_pct: float = 85.0
    puzzle_advantage_win_pct: float = 65.0

    # Lichess puzzle database (https://database.lichess.org/#puzzles).
    # The source may also be a local path to the .csv or .csv.zst file.
    puzzle_library_source: str = "https://database.lichess.org/lichess_db_puzzle.csv.zst"
    # Quality floor: net player vote (-100..100) and number of plays.
    puzzle_library_min_popularity: int = 50
    puzzle_library_min_plays: int = 50
    # Rows per insert statement (10 parameters each; Postgres allows 65535).
    puzzle_library_batch_size: int = 2000

    # Personal training: Lichess puzzles picked from your rating, mistakes
    # and playstyle (training/).
    # Puzzle rating (Glicko-1). The deviation starts wide so early results
    # move the rating quickly, and never drops below the floor so it keeps
    # adapting.
    puzzle_rating_default: float = 1500.0  # when there are no rated games to seed from
    puzzle_rating_initial_deviation: float = 250.0
    puzzle_rating_min_deviation: float = 70.0
    # Added to Chess.com game ratings when seeding: Lichess ratings run higher.
    puzzle_rating_chesscom_offset: float = 200.0
    # Recommended puzzles are rated within this many points of the user,
    # widening if too few match.
    training_rating_window: int = 100
    # How many of the most recent mistakes and blunders describe the user.
    training_mistake_sample: int = 600

    # HTTP clients
    lichess_base_url: str = "https://lichess.org"
    chesscom_base_url: str = "https://api.chess.com"
    http_user_agent: str = "chess-trainer/0.1"
    http_timeout_seconds: float = 30.0
    http_max_retries: int = 4

    # Worker
    worker_poll_seconds: float = 1.0
    # A running job whose heartbeat is older than this is assumed crashed.
    job_stale_seconds: float = 600.0

    @property
    def effective_puzzle_depth(self) -> int:
        return self.puzzle_depth or self.analysis_depth


@lru_cache
def get_settings() -> Settings:
    return Settings()
