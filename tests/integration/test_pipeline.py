import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from chess_trainer.analysis.cache import EvalCache, Evaluator, get_or_create_engine_config
from chess_trainer.analysis.classify import Thresholds
from chess_trainer.analysis.openings import load_opening_book
from chess_trainer.analysis.pipeline import analyze_game
from chess_trainer.db.enums import Classification, Color, Phase
from chess_trainer.db.models import Game, MoveAnalysis, PositionEval
from tests.fakes import FakeEngine

pytestmark = pytest.mark.integration


def analyze(session: Session, game: Game, engine: FakeEngine, depth: int = 12) -> None:
    config = get_or_create_engine_config(session, engine)
    evaluator = Evaluator(engine, EvalCache(session, config.id))
    analyze_game(session, game, evaluator, load_opening_book(), depth, Thresholds(), config.id)


def moves(session: Session, game: Game) -> list[MoveAnalysis]:
    stmt = select(MoveAnalysis).where(MoveAnalysis.game_id == game.id).order_by(MoveAnalysis.ply)
    return list(session.scalars(stmt))


def test_analysis_stores_one_row_per_move(
    session: Session, scholars_game: Game, engine: FakeEngine
) -> None:
    analyze(session, scholars_game, engine)

    rows = moves(session, scholars_game)
    assert [m.san for m in rows] == ["e4", "e5", "Bc4", "Nc6", "Qh5", "Nf6", "Qxf7#"]
    blunder = rows[5]
    assert blunder.color is Color.BLACK
    assert blunder.classification is Classification.BLUNDER
    assert blunder.best_move_san == "g6" and blunder.best_line == ["g7g6"]
    assert (blunder.eval_before_cp, blunder.eval_after_mate) == (-30, 1)
    assert blunder.phase is Phase.OPENING
    assert blunder.clock_remaining_s == 267 and blunder.time_spent_s == 30
    assert (blunder.eval_depth_before, blunder.eval_depth_after) == (12, 12)


def test_analysis_updates_game_metadata(
    session: Session, scholars_game: Game, engine: FakeEngine
) -> None:
    analyze(session, scholars_game, engine)
    game = scholars_game
    assert (game.eco, game.opening_name, game.opening_ply) == ("C23", "Bishop's Opening", 3)
    assert game.analyzed_depth == 12 and game.analyzed_at is not None
    assert game.analysis_engine_config_id is not None
    assert game.middlegame_start_ply is None and game.endgame_start_ply is None


def test_engine_is_called_once_per_non_terminal_position(
    session: Session, scholars_game: Game, engine: FakeEngine
) -> None:
    analyze(session, scholars_game, engine)
    # 7 moves = 8 positions; the last is checkmate and is scored from the rules.
    assert len(engine.calls) == 7
    assert session.scalar(select(func.count()).select_from(PositionEval)) == 7


def test_reanalysis_at_same_or_lower_depth_uses_only_the_cache(
    session: Session, scholars_game: Game, engine: FakeEngine
) -> None:
    analyze(session, scholars_game, engine, depth=12)
    engine.calls.clear()

    analyze(session, scholars_game, engine, depth=12)
    analyze(session, scholars_game, engine, depth=8)

    assert engine.calls == []
    assert len(moves(session, scholars_game)) == 7  # upserted, not duplicated


def test_deeper_reanalysis_recomputes_and_updates_rows_in_place(
    session: Session, scholars_game: Game, engine: FakeEngine
) -> None:
    analyze(session, scholars_game, engine, depth=12)
    ids_before = [m.id for m in moves(session, scholars_game)]
    engine.calls.clear()

    analyze(session, scholars_game, engine, depth=18)

    assert len(engine.calls) == 7
    session.expire_all()
    rows = moves(session, scholars_game)
    assert [m.id for m in rows] == ids_before  # same rows, so references stay valid
    assert {m.eval_depth_before for m in rows} == {18}
    assert scholars_game.analyzed_depth == 18


def test_a_different_engine_does_not_reuse_the_cache(
    session: Session, scholars_game: Game, engine: FakeEngine
) -> None:
    analyze(session, scholars_game, engine)
    upgraded = FakeEngine(engine.script, name="FakeFish 2")
    analyze(session, scholars_game, upgraded)
    assert len(upgraded.calls) == 7
