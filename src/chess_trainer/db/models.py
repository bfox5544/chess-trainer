"""SQLAlchemy models. See README "Data model" for the reasoning."""

from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from chess_trainer.db.base import Base, str_enum, utcnow
from chess_trainer.db.enums import (
    Classification,
    Color,
    JobKind,
    JobStatus,
    Phase,
    Platform,
    PuzzleOutcome,
    PuzzleSource,
    PuzzleStatus,
    TimeClass,
)


class User(Base):
    """A person using the trainer. Owns any number of platform accounts."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    display_name: Mapped[str] = mapped_column(sa.String(100))
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=utcnow)

    accounts: Mapped[list["ChessAccount"]] = relationship(back_populates="user")


class ChessAccount(Base):
    """One Lichess or Chess.com account, linked to a user."""

    __tablename__ = "chess_accounts"
    __table_args__ = (sa.UniqueConstraint("platform", "username"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(sa.ForeignKey("users.id", ondelete="CASCADE"), index=True)
    platform: Mapped[Platform] = mapped_column(str_enum(Platform))
    # Lowercased: both platforms treat usernames case-insensitively.
    username: Mapped[str] = mapped_column(sa.String(100))
    last_synced_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))

    user: Mapped[User] = relationship(back_populates="accounts")


class Game(Base):
    """A game, stored once no matter how many tracked accounts played in it."""

    __tablename__ = "games"
    __table_args__ = (sa.UniqueConstraint("platform", "platform_game_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    platform: Mapped[Platform] = mapped_column(str_enum(Platform))
    platform_game_id: Mapped[str] = mapped_column(sa.String(100))
    pgn: Mapped[str] = mapped_column(sa.Text)
    played_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), index=True)
    white_username: Mapped[str] = mapped_column(sa.String(100))
    black_username: Mapped[str] = mapped_column(sa.String(100))
    white_rating: Mapped[int | None]
    black_rating: Mapped[int | None]
    result: Mapped[str] = mapped_column(sa.String(10))
    time_class: Mapped[TimeClass] = mapped_column(str_enum(TimeClass))
    base_seconds: Mapped[int | None]
    increment_seconds: Mapped[int | None]
    ply_count: Mapped[int]
    # Opening: PGN headers at import, refined from the opening book at analysis.
    eco: Mapped[str | None] = mapped_column(sa.String(3))
    opening_name: Mapped[str | None] = mapped_column(sa.String(200))
    opening_family: Mapped[str | None] = mapped_column(sa.String(200), index=True)
    # Number of plies that stayed inside the opening book (set by analysis).
    opening_ply: Mapped[int | None]
    # First ply played in each phase; null if the game never reached it.
    middlegame_start_ply: Mapped[int | None]
    endgame_start_ply: Mapped[int | None]
    # What the stored move analyses were produced with; null = not analyzed.
    analysis_engine_config_id: Mapped[int | None] = mapped_column(
        sa.ForeignKey("engine_configs.id")
    )
    analyzed_depth: Mapped[int | None]
    analyzed_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=utcnow)


class AccountGame(Base):
    """Which tracked account played which color in a game."""

    __tablename__ = "account_games"

    account_id: Mapped[int] = mapped_column(
        sa.ForeignKey("chess_accounts.id", ondelete="CASCADE"), primary_key=True
    )
    game_id: Mapped[int] = mapped_column(
        sa.ForeignKey("games.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    color: Mapped[Color] = mapped_column(str_enum(Color))


class EngineConfig(Base):
    """An engine identity whose evaluations are comparable with each other.

    The fingerprint covers the engine name/version and every option that
    changes what the engine evaluates. Threads and hash size are excluded on
    purpose: they change speed, not meaning (see README).
    """

    __tablename__ = "engine_configs"

    id: Mapped[int] = mapped_column(primary_key=True)
    engine_name: Mapped[str] = mapped_column(sa.String(200))
    options: Mapped[dict[str, str]] = mapped_column(JSONB)
    fingerprint: Mapped[str] = mapped_column(sa.String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=utcnow)


class PositionEval(Base):
    """The analysis cache: one row per (position, engine config, line count)."""

    __tablename__ = "position_evals"

    # `board.epd()`: the position without move counters, so transpositions hit.
    position_key: Mapped[str] = mapped_column(sa.Text, primary_key=True)
    engine_config_id: Mapped[int] = mapped_column(
        sa.ForeignKey("engine_configs.id", ondelete="CASCADE"), primary_key=True
    )
    multipv: Mapped[int] = mapped_column(primary_key=True)
    depth: Mapped[int]
    # [{"cp": int|null, "mate": int|null, "pv": [uci, ...]}, ...] best line first,
    # scores from White's point of view.
    lines: Mapped[list[dict[str, object]]] = mapped_column(JSONB)
    updated_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=utcnow)


class MoveAnalysis(Base):
    """One analyzed move (both colors are stored; reports filter by color).

    Evals are copied from the cache at analysis time so reports need no joins
    and stay stable when the cache is later deepened. All evals are from
    White's point of view; win percentages are from the mover's.
    """

    __tablename__ = "move_analyses"
    __table_args__ = (sa.UniqueConstraint("game_id", "ply"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    game_id: Mapped[int] = mapped_column(sa.ForeignKey("games.id", ondelete="CASCADE"))
    ply: Mapped[int]  # 0-based: 0 is White's first move
    move_number: Mapped[int]
    color: Mapped[Color] = mapped_column(str_enum(Color))
    san: Mapped[str] = mapped_column(sa.String(10))
    uci: Mapped[str] = mapped_column(sa.String(5))
    fen_before: Mapped[str] = mapped_column(sa.String(100))
    eval_before_cp: Mapped[int | None]
    eval_before_mate: Mapped[int | None]
    eval_after_cp: Mapped[int | None]
    eval_after_mate: Mapped[int | None]
    eval_depth_before: Mapped[int]
    eval_depth_after: Mapped[int]
    best_move_uci: Mapped[str | None] = mapped_column(sa.String(5))
    best_move_san: Mapped[str | None] = mapped_column(sa.String(10))
    best_line: Mapped[list[str]] = mapped_column(JSONB)
    win_pct_before: Mapped[float]
    win_pct_after: Mapped[float]
    win_pct_loss: Mapped[float]
    classification: Mapped[Classification] = mapped_column(str_enum(Classification), index=True)
    is_best: Mapped[bool]
    is_forced: Mapped[bool]  # only one legal move
    in_book: Mapped[bool]
    phase: Mapped[Phase] = mapped_column(str_enum(Phase))
    clock_remaining_s: Mapped[float | None]
    time_spent_s: Mapped[float | None]


class Job(Base):
    """A background job. This table *is* the queue (see README)."""

    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[JobKind] = mapped_column(str_enum(JobKind))
    status: Mapped[JobStatus] = mapped_column(
        str_enum(JobStatus), default=JobStatus.QUEUED, index=True
    )
    params: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
    result: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    progress_done: Mapped[int] = mapped_column(default=0)
    progress_total: Mapped[int | None]
    parent_id: Mapped[int | None] = mapped_column(sa.ForeignKey("jobs.id"), index=True)
    error: Mapped[str | None] = mapped_column(sa.Text)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))


class Puzzle(Base):
    """A puzzle candidate from one of the user's own mistakes.

    Rejected candidates are kept (with a reason) so thresholds can be tuned by
    querying instead of re-analyzing. Keyed by (game, ply) so re-analysis
    updates a puzzle in place and its id stays valid for future attempt
    history (see README "Designed for later").
    """

    __tablename__ = "puzzles"
    __table_args__ = (sa.UniqueConstraint("game_id", "ply"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[PuzzleSource] = mapped_column(
        str_enum(PuzzleSource), default=PuzzleSource.OWN_GAME
    )
    user_id: Mapped[int] = mapped_column(sa.ForeignKey("users.id", ondelete="CASCADE"), index=True)
    account_id: Mapped[int] = mapped_column(sa.ForeignKey("chess_accounts.id", ondelete="CASCADE"))
    game_id: Mapped[int] = mapped_column(sa.ForeignKey("games.id", ondelete="CASCADE"))
    ply: Mapped[int]
    status: Mapped[PuzzleStatus] = mapped_column(str_enum(PuzzleStatus), index=True)
    reject_reason: Mapped[str | None] = mapped_column(sa.String(50))
    # The position to solve and who solves it.
    fen: Mapped[str] = mapped_column(sa.String(100))
    user_color: Mapped[Color] = mapped_column(str_enum(Color))
    phase: Mapped[Phase] = mapped_column(str_enum(Phase))
    # What the user actually played, and what it cost.
    played_uci: Mapped[str] = mapped_column(sa.String(5))
    played_san: Mapped[str] = mapped_column(sa.String(10))
    played_win_pct: Mapped[float]
    severity: Mapped[Classification] = mapped_column(str_enum(Classification))
    # The full solution: user moves alternating with the opponent's best
    # replies, each with its evaluation. Always ends on a user move.
    # [{"uci", "san", "by": "user"|"opponent", "cp", "mate", "win_pct",
    #   "second_best_uci", "second_best_win_pct"}, ...]
    solution: Mapped[list[dict[str, object]]] = mapped_column(JSONB)
    solution_plies: Mapped[int]
    outcome: Mapped[PuzzleOutcome | None] = mapped_column(str_enum(PuzzleOutcome))
    # Win-% gap between the best and second-best first move (null: only one move).
    uniqueness_gap: Mapped[float | None]
    # Provenance, for re-validation when the engine or generator changes.
    engine_config_id: Mapped[int] = mapped_column(sa.ForeignKey("engine_configs.id"))
    depth: Mapped[int]
    generator_version: Mapped[int]
    # Tactical motifs; stays empty until taggers exist (reports/motifs.py).
    themes: Mapped[list[str]] = mapped_column(JSONB, default=list)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=utcnow)
