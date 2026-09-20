"""Analyze one stored game end to end and persist the result."""

from dataclasses import asdict

import chess
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from chess_trainer.analysis.cache import Evaluator
from chess_trainer.analysis.classify import Thresholds
from chess_trainer.analysis.engine import PositionEvaluation
from chess_trainer.analysis.highlights import (
    HIGHLIGHTS_VERSION,
    HighlightConfig,
    MoveSituation,
    is_brilliant,
    is_great,
    needs_second_line,
)
from chess_trainer.analysis.moves import GameContext, MoveRecord, build_move_records
from chess_trainer.analysis.openings import OpeningBook
from chess_trainer.analysis.phase import first_ply_in, game_phases
from chess_trainer.analysis.replay import Replay, replay_pgn
from chess_trainer.analysis.winprob import win_pct
from chess_trainer.db.base import utcnow
from chess_trainer.db.enums import Highlight, Phase
from chess_trainer.db.models import Game, MoveAnalysis
from chess_trainer.reports.game_report import tracked_colors


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


def mark_highlights(
    session: Session, game: Game, evaluator: Evaluator, config: HighlightConfig, depth: int
) -> int:
    """Mark the tracked accounts' great and brilliant moves in an analyzed
    game. Only moves that could be great cost an engine search (a second
    line). Returns how many moves were marked."""
    colors = tracked_colors(session, game.id)
    stmt = select(MoveAnalysis).where(MoveAnalysis.game_id == game.id).order_by(MoveAnalysis.ply)
    moves = list(session.scalars(stmt))
    plies = replay_pgn(game.pgn).plies if moves else []
    marked = 0
    for move in moves:
        move.highlight, move.second_best_san, move.second_best_win_pct = None, None, None
        if move.color not in colors or move.ply >= len(plies):
            continue
        ply = plies[move.ply]
        situation = MoveSituation(
            board=ply.board_before,
            move=ply.move,
            previous=plies[move.ply - 1].move if move.ply > 0 else None,
            is_best=move.is_best,
            is_forced=move.is_forced,
            in_book=move.in_book,
            win_pct_before=move.win_pct_before,
            win_pct_after=move.win_pct_after,
            win_pct_loss=move.win_pct_loss,
        )
        if is_brilliant(situation, config):
            move.highlight = Highlight.BRILLIANT
        elif needs_second_line(situation, config):
            mark_if_great(move, situation, evaluator.evaluate(ply.board_before, depth, 2), config)
        marked += move.highlight is not None
    game.highlights_version = HIGHLIGHTS_VERSION
    session.flush()
    return marked


def mark_if_great(
    move: MoveAnalysis,
    situation: MoveSituation,
    evaluation: PositionEvaluation,
    config: HighlightConfig,
) -> None:
    board, mover = situation.board, situation.board.turn
    if len(evaluation.lines) < 2 or not evaluation.lines[1].pv:
        return
    best, second = evaluation.lines[0], evaluation.lines[1]
    if best.pv[:1] != (situation.move.uci(),):  # the deeper look prefers another move
        return
    second_pct = win_pct(second.eval, mover)
    if is_great(win_pct(best.eval, mover), second_pct, config):
        move.highlight = Highlight.GREAT
        move.second_best_san = board.san(chess.Move.from_uci(second.pv[0]))
        move.second_best_win_pct = round(second_pct, 1)
