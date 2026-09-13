"""Score moves live with the engine: "keep playing" after a puzzle or from a
repeated mistake."""

from collections.abc import Callable
from typing import TypeVar

import chess.engine
from fastapi import APIRouter, HTTPException, status
from sqlalchemy.orm import Session

from chess_trainer.analysis.cache import EvalCache, Evaluator, get_or_create_engine_config
from chess_trainer.analysis.live import MoveScore, best_move, score_move
from chess_trainer.api.deps import EngineDep, SessionDep, SettingsDep, SharedEngine
from chess_trainer.api.schemas import (
    EngineMoveOut,
    EngineReplyOut,
    MoveScoreIn,
    MoveScoreOut,
    PositionIn,
    ReasonOut,
)
from chess_trainer.jobs.handlers import thresholds_from

router = APIRouter(prefix="/analysis", tags=["analysis"])
T = TypeVar("T")


def with_evaluator(shared: SharedEngine, session: Session, run: Callable[[Evaluator], T]) -> T:
    """Run `run` with the shared engine, one request at a time. 422 for an
    illegal position or move, 503 if the engine cannot be started or dies."""
    with shared.lock:
        try:
            engine = shared.get()
            config = get_or_create_engine_config(session, engine)
            return run(Evaluator(engine, EvalCache(session, config.id)))
        except ValueError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
        except (OSError, chess.engine.EngineError, chess.engine.EngineTerminatedError) as exc:
            shared.discard()
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE, "the chess engine is not available"
            ) from exc


def score_out(score: MoveScore) -> MoveScoreOut:
    return MoveScoreOut(
        uci=score.uci,
        san=score.san,
        color=score.color,
        move_number=score.move_number,
        fen_before=score.fen_before,
        fen_after=score.fen_after,
        classification=score.classification,
        is_best=score.is_best,
        is_forced=score.is_forced,
        in_book=score.in_book,
        win_pct_before=score.win_pct_before,
        win_pct_after=score.win_pct_after,
        win_pct_loss=score.win_pct_loss,
        eval_after_cp=score.eval_after.cp,
        eval_after_mate=score.eval_after.mate,
        best_move_uci=score.best_move_uci,
        best_move_san=score.best_move_san,
        best_line=score.best_line,
        explanation=[ReasonOut.model_validate(reason) for reason in score.explanation],
        reply=EngineMoveOut.model_validate(score.reply) if score.reply else None,
    )


@router.post("/move", response_model=MoveScoreOut)
def score(
    body: MoveScoreIn, session: SessionDep, settings: SettingsDep, shared: EngineDep
) -> MoveScoreOut:
    """Classify a move played in any position, exactly as game analysis
    would (same thresholds, same explanations), and return the engine's
    reply. Evaluations are cached like those of analyzed games."""
    found = with_evaluator(
        shared,
        session,
        lambda evaluator: score_move(
            evaluator, body.fen, body.uci, settings.effective_live_depth, thresholds_from(settings)
        ),
    )
    return score_out(found)


@router.post("/reply", response_model=EngineReplyOut)
def reply(
    body: PositionIn, session: SessionDep, settings: SettingsDep, shared: EngineDep
) -> EngineReplyOut:
    """The engine's move in a position, for when it is the engine's turn
    first. `move` is null if the game is over."""
    found = with_evaluator(
        shared,
        session,
        lambda evaluator: best_move(evaluator, body.fen, settings.effective_live_depth),
    )
    return EngineReplyOut(move=EngineMoveOut.model_validate(found) if found else None)
