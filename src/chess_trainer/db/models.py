"""SQLAlchemy models. See README "Data model" for the reasoning."""

from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from chess_trainer.db.base import Base, str_enum, utcnow
from chess_trainer.db.enums import Color, Platform, TimeClass


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
