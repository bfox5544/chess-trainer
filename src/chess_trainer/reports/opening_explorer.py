"""One opening, explored: its main line and the user's games that reached it.

The Stats page groups moves by opening family; this report backs the page
that opens when you click one. The games carry only a summary and the plies
where the user went wrong; the client loads a game's full analysis (with
explanations) when it is opened.
"""

from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass

import chess
from sqlalchemy import select
from sqlalchemy.orm import Session

from chess_trainer.analysis.openings import OpeningBook, load_opening_book
from chess_trainer.db.enums import Classification, Color, Phase
from chess_trainer.db.models import AccountGame, ChessAccount, Game, MoveAnalysis
from chess_trainer.reports.stats import MoveStats, summarize
from chess_trainer.reports.user_games import outcome_for, stats_by_side
from chess_trainer.reports.weakness import UNKNOWN_OPENING, WeaknessFilters

ERRORS = (Classification.INACCURACY, Classification.MISTAKE, Classification.BLUNDER)
# Named positions sit early in a game; scanning further only costs time.
MAX_LINE_PLIES = 30


@dataclass(frozen=True)
class LineStep:
    uci: str
    san: str


@dataclass(frozen=True)
class OpeningLine:
    name: str | None  # name of the line's final position in the opening book
    steps: list[LineStep]


@dataclass(frozen=True)
class GameError:
    ply: int
    move_number: int
    san: str
    best_move_san: str | None
    classification: Classification
    phase: Phase
    win_pct_loss: float


@dataclass(frozen=True)
class OpeningGame:
    game: Game
    user_color: Color
    outcome: str | None
    stats: MoveStats | None
    errors: list[GameError]  # the user's inaccuracies, mistakes and blunders, in order


@dataclass(frozen=True)
class OpeningExplorer:
    family: str
    line: OpeningLine
    stats: MoveStats  # the user's moves across these games
    games: list[OpeningGame]  # newest first


def entry_line(ucis: Sequence[str], family: str, book: OpeningBook) -> list[str] | None:
    """Moves of this game up to the position that names `family`.

    Prefers the position named exactly after the family ("Caro-Kann Defense"
    after 1.e4 c6), falling back to the first position of the family. None if
    the game never reaches a position of the family.
    """
    board = chess.Board()
    first: list[str] | None = None
    for index, uci in enumerate(ucis[:MAX_LINE_PLIES]):
        try:
            board.push_uci(uci)
        except ValueError:
            break
        opening = book.lookup(board)
        if opening is None or opening.family != family:
            continue
        if opening.name == family:
            return list(ucis[: index + 1])
        if first is None:
            first = list(ucis[: index + 1])
    return first


def main_line(games: Sequence[Sequence[str]], family: str, book: OpeningBook) -> OpeningLine:
    """The entry line most of the games share; on a tie, the shorter one."""
    lines = Counter(tuple(line) for ucis in games if (line := entry_line(ucis, family, book)))
    if not lines:
        return OpeningLine(None, [])
    best = max(lines, key=lambda line: (lines[line], -len(line)))
    board = chess.Board()
    steps = []
    for uci in best:
        move = chess.Move.from_uci(uci)
        steps.append(LineStep(uci, board.san(move)))
        board.push(move)
    found = book.lookup(board)
    return OpeningLine(found.name if found else None, steps)


def opening_games(
    session: Session, user_id: int, family: str, filters: WeaknessFilters, limit: int
) -> list[tuple[Game, Color]]:
    """The user's analyzed games in this opening family, newest first."""
    conditions = [ChessAccount.user_id == user_id, Game.analyzed_depth.is_not(None)]
    if family == UNKNOWN_OPENING:
        conditions.append(Game.opening_family.is_(None))
    else:
        conditions.append(Game.opening_family == family)
    if filters.account_id is not None:
        conditions.append(ChessAccount.id == filters.account_id)
    if filters.time_class is not None:
        conditions.append(Game.time_class == filters.time_class)
    if filters.since is not None:
        conditions.append(Game.played_at >= filters.since)
    stmt = (
        select(Game, AccountGame.color)
        .join(AccountGame, AccountGame.game_id == Game.id)
        .join(ChessAccount, ChessAccount.id == AccountGame.account_id)
        .where(*conditions)
        .order_by(Game.played_at.desc().nulls_last(), Game.id.desc())
        .limit(limit)
    )
    return [(game, color) for game, color in session.execute(stmt).all()]


def load_moves(session: Session, game_ids: list[int]) -> dict[int, list[MoveAnalysis]]:
    stmt = (
        select(MoveAnalysis)
        .where(MoveAnalysis.game_id.in_(game_ids))
        .order_by(MoveAnalysis.game_id, MoveAnalysis.ply)
    )
    moves: dict[int, list[MoveAnalysis]] = defaultdict(list)
    for move in session.scalars(stmt):
        moves[move.game_id].append(move)
    return moves


def errors_of(moves: Sequence[MoveAnalysis], color: Color) -> list[GameError]:
    return [
        GameError(
            m.ply, m.move_number, m.san, m.best_move_san, m.classification, m.phase, m.win_pct_loss
        )
        for m in moves
        if m.color is color and not m.is_forced and m.classification in ERRORS
    ]


def build_opening_explorer(
    session: Session,
    user_id: int,
    family: str,
    filters: WeaknessFilters,
    limit: int = 50,
    book: OpeningBook | None = None,
) -> OpeningExplorer | None:
    """None if the user has no analyzed games in this opening."""
    rows = opening_games(session, user_id, family, filters, limit)
    if not rows:
        return None
    ids = [game.id for game, _ in rows]
    moves = load_moves(session, ids)
    stats = stats_by_side(session, ids)
    line = (
        OpeningLine(None, [])
        if family == UNKNOWN_OPENING
        else main_line(
            [[m.uci for m in moves[i][:MAX_LINE_PLIES]] for i in ids],
            family,
            book or load_opening_book(),
        )
    )
    mine = [
        (m.classification, m.win_pct_loss)
        for game, color in rows
        for m in moves[game.id]
        if m.color is color and not m.is_forced
    ]
    games = [
        OpeningGame(
            game,
            color,
            outcome_for(game.result, color),
            stats.get((game.id, color)),
            errors_of(moves[game.id], color),
        )
        for game, color in rows
    ]
    return OpeningExplorer(family, line, summarize(mine), games)
