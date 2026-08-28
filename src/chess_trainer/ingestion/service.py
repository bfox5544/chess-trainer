"""Fetch -> normalize -> de-duplicate -> store."""

from collections import Counter
from dataclasses import asdict, dataclass, field

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from chess_trainer.db.base import utcnow
from chess_trainer.db.enums import Color
from chess_trainer.db.models import AccountGame, ChessAccount, Game
from chess_trainer.ingestion.normalize import NormalizedGame, SkipReason, normalize
from chess_trainer.ingestion.sources import FetchFilters, GameSource

NOT_A_PARTICIPANT = "not_a_participant"


@dataclass
class ImportResult:
    fetched: int = 0
    stored: int = 0  # new game rows
    already_stored: int = 0
    skipped: Counter[str] = field(default_factory=Counter)  # reason -> count

    def as_dict(self) -> dict[str, object]:
        return {**asdict(self), "skipped": dict(self.skipped)}


def import_games(
    session: Session, account: ChessAccount, source: GameSource, filters: FetchFilters
) -> ImportResult:
    """Import an account's recent games. Safe to re-run: duplicates are skipped."""
    result = ImportResult()
    for raw in source.fetch_games(account.username, filters):
        result.fetched += 1
        game = normalize(raw)
        if isinstance(game, SkipReason):
            result.skipped[game.value] += 1
            continue
        color = color_of(account.username, game)
        if color is None:
            result.skipped[NOT_A_PARTICIPANT] += 1
            continue
        game_id, created = store_game(session, game)
        link_account_game(session, account.id, game_id, color)
        result.stored += created
        result.already_stored += not created
    account.last_synced_at = utcnow()
    session.flush()
    return result


def color_of(username: str, game: NormalizedGame) -> Color | None:
    name = username.lower()
    if game.white_username.lower() == name:
        return Color.WHITE
    if game.black_username.lower() == name:
        return Color.BLACK
    return None


def store_game(session: Session, game: NormalizedGame) -> tuple[int, bool]:
    """Insert the game unless it exists. Returns (game id, was it new?).

    `ON CONFLICT DO NOTHING` makes the uniqueness check atomic, so two
    concurrent imports of the same game can't both insert it.
    """
    stmt = (
        insert(Game)
        .values(**asdict(game))
        .on_conflict_do_nothing(index_elements=["platform", "platform_game_id"])
        .returning(Game.id)
    )
    new_id = session.execute(stmt).scalar_one_or_none()
    if new_id is not None:
        return new_id, True
    existing = select(Game.id).where(
        Game.platform == game.platform, Game.platform_game_id == game.platform_game_id
    )
    return session.execute(existing).scalar_one(), False


def link_account_game(session: Session, account_id: int, game_id: int, color: Color) -> None:
    stmt = (
        insert(AccountGame)
        .values(account_id=account_id, game_id=game_id, color=color)
        .on_conflict_do_nothing()
    )
    session.execute(stmt)
