"""The user's recent mistakes and blunders, tagged with tactical motifs.

Motifs are computed at read time from the stored engine lines, the same way
move explanations are, so every game analyzed before taggers existed is
covered and changing `analysis/motifs.py` needs no migration.
"""

from dataclasses import dataclass

from sqlalchemy import and_
from sqlalchemy.orm import Session, aliased

from chess_trainer.analysis.explain import MoveFacts
from chess_trainer.analysis.motifs import MistakeMotifs, mistake_motifs
from chess_trainer.db.enums import Classification, Phase
from chess_trainer.db.models import Game, MoveAnalysis
from chess_trainer.reports.game_report import stored_eval
from chess_trainer.reports.weakness import WeaknessFilters, user_moves_query

SERIOUS = (Classification.MISTAKE, Classification.BLUNDER)


@dataclass(frozen=True)
class Mistake:
    game_id: int
    phase: Phase
    motifs: MistakeMotifs


def load_mistakes(session: Session, user_id: int, limit: int) -> list[Mistake]:
    """The user's `limit` most recent mistakes and blunders. Inaccuracies
    are left out: they are rarely tactical."""
    following = aliased(MoveAnalysis)
    previous = aliased(MoveAnalysis)
    stmt = (
        user_moves_query(user_id, WeaknessFilters())
        .outerjoin(
            following,
            and_(following.game_id == MoveAnalysis.game_id, following.ply == MoveAnalysis.ply + 1),
        )
        .outerjoin(
            previous,
            and_(previous.game_id == MoveAnalysis.game_id, previous.ply == MoveAnalysis.ply - 1),
        )
        .add_columns(MoveAnalysis, following.best_line, previous.fen_before, previous.uci)
        .where(MoveAnalysis.classification.in_(SERIOUS))
        .order_by(Game.played_at.desc().nulls_last(), Game.id.desc(), MoveAnalysis.ply)
        .limit(limit)
    )
    mistakes = []
    for move, reply_line, previous_fen, previous_uci in session.execute(stmt):
        facts = MoveFacts(
            fen_before=move.fen_before,
            uci=move.uci,
            classification=move.classification,
            is_best=move.is_best,
            eval_before=stored_eval(move.eval_before_cp, move.eval_before_mate),
            eval_after=stored_eval(move.eval_after_cp, move.eval_after_mate),
            best_line=move.best_line,
            reply_line=reply_line or [],
            previous_fen=previous_fen,
            previous_uci=previous_uci,
        )
        mistakes.append(Mistake(move.game_id, move.phase, mistake_motifs(facts)))
    return mistakes
