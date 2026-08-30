"""Analyze one stored game end to end and persist the result."""

from dataclasses import asdict

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from chess_trainer.analysis.cache import Evaluator
from chess_trainer.analysis.classify import Thresholds
from chess_trainer.analysis.moves import GameContext, MoveRecord, build_move_records
from chess_trainer.analysis.openings import OpeningBook
from chess_trainer.analysis.phase import first_ply_in, game_phases
from chess_trainer.analysis.replay import Replay, replay_pgn
from chess_trainer.db.base import utcnow
from chess_trainer.db.enums import Phase
from chess_trainer.db.models import Game, MoveAnalysis


def analyze_game(
    session: Session,
    game: Game,
    evaluator: Evaluator,
    book: OpeningBook,
    depth: int,
    thresholds: Thresholds,
    engine_config_id: int,
) -> list[MoveRecord]:
    """Evaluate every position, classify every move, and store the rows.

    Idempotent: rows are upserted by (game, ply), so re-analysis at a greater
    depth updates in place and anything referencing a move keeps working.
    """
    replay = replay_pgn(game.pgn)
    boards = replay.boards
    evaluations = evaluator.evaluate_many(boards, depth)
    phases = game_phases(boards)
    opening_ply = apply_opening(game, book, replay)
    context = GameContext(thresholds, opening_ply, game.base_seconds, game.increment_seconds)
    records = build_move_records(replay.plies, evaluations, phases, context)
    upsert_moves(session, game.id, records)
    game.middlegame_start_ply = first_ply_in(phases, Phase.MIDDLEGAME)
    game.endgame_start_ply = first_ply_in(phases, Phase.ENDGAME)
    game.analysis_engine_config_id = engine_config_id
    game.analyzed_depth = depth
    game.analyzed_at = utcnow()
    session.flush()
    return records


def apply_opening(game: Game, book: OpeningBook, replay: Replay) -> int:
    """Set the game's opening from the book; keep PGN-header values if no match."""
    match = book.deepest_match(replay.boards)
    game.opening_ply = match.ply if match else 0
    if match:
        game.eco = match.opening.eco
        game.opening_name = match.opening.name
        game.opening_family = match.opening.family
    return game.opening_ply


def move_row(game_id: int, record: MoveRecord) -> dict[str, object]:
    row = asdict(record)
    before, after = row.pop("eval_before"), row.pop("eval_after")
    return {
        **row,
        "game_id": game_id,
        "eval_before_cp": before["cp"],
        "eval_before_mate": before["mate"],
        "eval_after_cp": after["cp"],
        "eval_after_mate": after["mate"],
    }


def upsert_moves(session: Session, game_id: int, records: list[MoveRecord]) -> None:
    if not records:
        return
    stmt = insert(MoveAnalysis).values([move_row(game_id, record) for record in records])
    updatable = {
        column.name: stmt.excluded[column.name]
        for column in MoveAnalysis.__table__.columns
        if column.name not in {"id", "game_id", "ply"}
    }
    session.execute(stmt.on_conflict_do_update(index_elements=["game_id", "ply"], set_=updatable))
