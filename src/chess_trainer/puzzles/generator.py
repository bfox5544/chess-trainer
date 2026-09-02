"""Create and refresh the puzzles of one analyzed game."""

from dataclasses import asdict

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from chess_trainer.analysis.cache import Evaluator
from chess_trainer.analysis.replay import replay_pgn
from chess_trainer.config import Settings
from chess_trainer.db.base import utcnow
from chess_trainer.db.enums import Classification, PuzzleStatus
from chess_trainer.db.models import AccountGame, ChessAccount, Game, MoveAnalysis, Puzzle
from chess_trainer.puzzles.builder import (
    GENERATOR_VERSION,
    PuzzleConfig,
    PuzzleDraft,
    build_puzzle,
)
from chess_trainer.reports.motifs import tag_motifs

PUZZLE_SEVERITIES = (Classification.MISTAKE, Classification.BLUNDER)
NO_LONGER_A_MISTAKE = "no_longer_a_mistake"


def puzzle_config_from(settings: Settings) -> PuzzleConfig:
    return PuzzleConfig(
        uniqueness_gap=settings.puzzle_uniqueness_gap,
        min_result_win_pct=settings.puzzle_min_result_win_pct,
        max_plies=settings.puzzle_max_plies,
        crushing_win_pct=settings.puzzle_crushing_win_pct,
        advantage_win_pct=settings.puzzle_advantage_win_pct,
    )


def candidate_moves(session: Session, game_id: int) -> list[tuple[MoveAnalysis, ChessAccount]]:
    """Mistakes and blunders made by a tracked account in this game."""
    stmt = (
        select(MoveAnalysis, ChessAccount)
        .join(
            AccountGame,
            (AccountGame.game_id == MoveAnalysis.game_id)
            & (AccountGame.color == MoveAnalysis.color),
        )
        .join(ChessAccount, ChessAccount.id == AccountGame.account_id)
        .where(
            MoveAnalysis.game_id == game_id,
            MoveAnalysis.classification.in_(PUZZLE_SEVERITIES),
            MoveAnalysis.is_forced.is_(False),
        )
        .order_by(MoveAnalysis.ply)
    )
    return [(move, account) for move, account in session.execute(stmt)]


def generate_puzzles_for_game(
    session: Session,
    game: Game,
    evaluator: Evaluator,
    config: PuzzleConfig,
    depth: int,
    engine_config_id: int,
) -> int:
    """Build a puzzle for each of the game's candidate mistakes.

    Upserts by (game, ply): re-running after a deeper analysis refreshes
    puzzles in place instead of replacing them. Returns how many were accepted.
    """
    candidates = candidate_moves(session, game.id)
    plies = replay_pgn(game.pgn).plies if candidates else []
    accepted = 0
    for move, account in candidates:
        board = plies[move.ply].board_before
        draft = build_puzzle(
            board, plies[move.ply].move, lambda b, k: evaluator.evaluate(b, depth, k), config
        )
        themes = tag_motifs(board, plies[move.ply].move, draft.moves) if draft.accepted else []
        upsert_puzzle(session, puzzle_row(move, account, draft, themes, depth, engine_config_id))
        accepted += draft.accepted
    retire_stale_puzzles(session, game.id, [move.ply for move, _ in candidates])
    session.flush()
    return accepted


def puzzle_row(
    move: MoveAnalysis,
    account: ChessAccount,
    draft: PuzzleDraft,
    themes: list[str],
    depth: int,
    engine_config_id: int,
) -> dict[str, object]:
    return {
        "user_id": account.user_id,
        "account_id": account.id,
        "game_id": move.game_id,
        "ply": move.ply,
        "status": PuzzleStatus.ACCEPTED if draft.accepted else PuzzleStatus.REJECTED,
        "reject_reason": draft.reject_reason,
        "fen": move.fen_before,
        "user_color": move.color,
        "phase": move.phase,
        "played_uci": move.uci,
        "played_san": move.san,
        "played_win_pct": round(move.win_pct_after, 1),
        "severity": move.classification,
        "solution": [asdict(step) for step in draft.solution],
        "solution_plies": len(draft.solution),
        "outcome": draft.outcome,
        "uniqueness_gap": None if draft.uniqueness_gap is None else round(draft.uniqueness_gap, 1),
        "engine_config_id": engine_config_id,
        "depth": depth,
        "generator_version": GENERATOR_VERSION,
        "themes": themes,
        "updated_at": utcnow(),
    }


def upsert_puzzle(session: Session, row: dict[str, object]) -> None:
    stmt = insert(Puzzle).values(**row)
    updatable = {key: stmt.excluded[key] for key in row if key not in {"game_id", "ply"}}
    session.execute(stmt.on_conflict_do_update(index_elements=["game_id", "ply"], set_=updatable))


def retire_stale_puzzles(session: Session, game_id: int, candidate_plies: list[int]) -> None:
    """Reject puzzles whose move a newer analysis no longer calls a mistake.

    Marked rather than deleted so anything that references the puzzle (future
    attempt history) is not orphaned.
    """
    stmt = (
        update(Puzzle)
        .where(
            Puzzle.game_id == game_id,
            Puzzle.ply.not_in(candidate_plies),
            Puzzle.status == PuzzleStatus.ACCEPTED,
        )
        .values(
            status=PuzzleStatus.REJECTED, reject_reason=NO_LONGER_A_MISTAKE, updated_at=utcnow()
        )
    )
    session.execute(stmt)
