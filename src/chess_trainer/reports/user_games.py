"""A user's games across all linked accounts, with how the user did in each."""

from collections import defaultdict
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from chess_trainer.db.enums import Classification, Color
from chess_trainer.db.models import AccountGame, ChessAccount, Game, MoveAnalysis
from chess_trainer.reports.stats import MoveStats, summarize

WINNING_RESULT = {Color.WHITE: "1-0", Color.BLACK: "0-1"}


@dataclass(frozen=True)
class UserGame:
    game: Game
    account_id: int
    user_color: Color
    outcome: str | None  # "win", "loss", "draw"; None if the game has no result
    stats: MoveStats | None  # the user's own moves; None until analyzed


def outcome_for(result: str, color: Color) -> str | None:
    if result == "1/2-1/2":
        return "draw"
    if result not in WINNING_RESULT.values():
        return None
    return "win" if result == WINNING_RESULT[color] else "loss"


def list_user_games(
    session: Session, user_id: int, account_id: int | None = None, limit: int = 20, offset: int = 0
) -> list[UserGame]:
    """Newest first. One row per (game, linked account)."""
    conditions = [ChessAccount.user_id == user_id]
    if account_id is not None:
        conditions.append(ChessAccount.id == account_id)
    stmt = (
        select(Game, AccountGame.account_id, AccountGame.color)
        .join(AccountGame, AccountGame.game_id == Game.id)
        .join(ChessAccount, ChessAccount.id == AccountGame.account_id)
        .where(*conditions)
        .order_by(Game.played_at.desc().nulls_last(), Game.id.desc())
        .limit(limit)
        .offset(offset)
    )
    rows = session.execute(stmt).all()
    stats = stats_by_side(session, [game.id for game, _, _ in rows])
    return [
        UserGame(game, account, color, outcome_for(game.result, color), stats.get((game.id, color)))
        for game, account, color in rows
    ]


def stats_by_side(session: Session, game_ids: list[int]) -> dict[tuple[int, Color], MoveStats]:
    """Move stats for each (game, color), from one query. Forced moves are left
    out, as in the weakness report."""
    if not game_ids:
        return {}
    stmt = select(
        MoveAnalysis.game_id,
        MoveAnalysis.color,
        MoveAnalysis.classification,
        MoveAnalysis.win_pct_loss,
    ).where(MoveAnalysis.game_id.in_(game_ids), MoveAnalysis.is_forced.is_(False))
    moves: dict[tuple[int, Color], list[tuple[Classification, float]]] = defaultdict(list)
    for game_id, color, classification, loss in session.execute(stmt):
        moves[(game_id, color)].append((classification, loss))
    return {side: summarize(pairs) for side, pairs in moves.items()}
