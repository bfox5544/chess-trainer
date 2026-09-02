import chess
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from chess_trainer.accounts.service import create_user, link_account
from chess_trainer.config import Settings
from chess_trainer.db.enums import (
    Classification,
    Color,
    JobKind,
    Phase,
    Platform,
    PuzzleOutcome,
    PuzzleStatus,
)
from chess_trainer.db.models import ChessAccount, Game, Puzzle
from chess_trainer.ingestion.service import import_games
from chess_trainer.ingestion.sources import FetchFilters
from chess_trainer.jobs import queue
from chess_trainer.jobs.handlers import JobContext
from chess_trainer.jobs.worker import work_once
from chess_trainer.puzzles.service import PuzzleFilters, list_puzzles
from chess_trainer.reports import motifs
from chess_trainer.reports.weakness import WeaknessFilters, build_weakness_report
from tests.fakes import FakeEngine, StubSource, position_after

pytestmark = pytest.mark.integration


def run_analysis(session: Session, account: ChessAccount, context: JobContext, depth: int) -> None:
    queue.enqueue(session, JobKind.ANALYZE, {"account_id": account.id, "depth": depth})
    assert work_once(session, context)


def all_puzzles(session: Session) -> list[Puzzle]:
    session.expire_all()
    return list(session.scalars(select(Puzzle).order_by(Puzzle.id)))


def test_blunder_becomes_a_complete_playable_puzzle(
    session: Session, bob: ChessAccount, scholars_game: Game, job_context: JobContext
) -> None:
    run_analysis(session, bob, job_context, depth=12)

    (puzzle,) = all_puzzles(session)
    assert puzzle.status is PuzzleStatus.ACCEPTED and puzzle.reject_reason is None
    assert (puzzle.user_id, puzzle.account_id, puzzle.game_id) == (
        bob.user_id,
        bob.id,
        scholars_game.id,
    )
    assert puzzle.ply == 5 and puzzle.user_color is Color.BLACK
    assert puzzle.fen == position_after("e4", "e5", "Bc4", "Nc6", "Qh5").fen()
    assert (puzzle.played_san, puzzle.played_uci, puzzle.played_win_pct) == ("Nf6", "g8f6", 0.0)
    assert puzzle.severity is Classification.BLUNDER and puzzle.phase is Phase.OPENING
    assert puzzle.outcome is PuzzleOutcome.EQUALIZE
    assert puzzle.solution_plies == 1 and puzzle.themes == []
    step = puzzle.solution[0]
    assert (step["san"], step["uci"], step["by"]) == ("g6", "g7g6", "user")
    assert step["second_best_uci"] == "d8e7"
    assert (puzzle.depth, puzzle.generator_version) == (16, 1)  # default PUZZLE_DEPTH floor
    # The stored line really is playable from the stored position.
    board = chess.Board(puzzle.fen)
    for move in puzzle.solution:
        board.push_uci(str(move["uci"]))


def test_reanalysis_keeps_the_puzzle_id(
    session: Session, bob: ChessAccount, scholars_game: Game, job_context: JobContext
) -> None:
    run_analysis(session, bob, job_context, depth=12)
    (before,) = all_puzzles(session)
    original_id = before.id

    run_analysis(session, bob, job_context, depth=20)

    (after,) = all_puzzles(session)
    assert after.id == original_id
    assert after.depth == 20 and after.status is PuzzleStatus.ACCEPTED


def test_puzzle_is_retired_when_a_newer_analysis_clears_the_move(
    session: Session, bob: ChessAccount, scholars_game: Game, job_context: JobContext
) -> None:
    run_analysis(session, bob, job_context, depth=12)
    # A new engine version that sees nothing wrong with any move.
    job_context.get_engine = lambda: FakeEngine(name="FakeFish 2")

    run_analysis(session, bob, job_context, depth=12)

    (puzzle,) = all_puzzles(session)
    assert puzzle.status is PuzzleStatus.REJECTED
    assert puzzle.reject_reason == "no_longer_a_mistake"
    assert list_puzzles(session, bob.user_id, PuzzleFilters()) == []


def test_rejected_candidates_are_stored_with_a_reason_but_not_listed(
    session: Session,
    bob: ChessAccount,
    scholars_game: Game,
    job_context: JobContext,
    engine: FakeEngine,
) -> None:
    # Make 3...Qe7 nearly as good as 3...g6, so the blunder has no single answer.
    key = position_after("e4", "e5", "Bc4", "Nc6", "Qh5").epd()
    engine.script[key] = [engine.script[key][0], ("d8e7", engine.script[key][0][1])]

    run_analysis(session, bob, job_context, depth=12)

    (puzzle,) = all_puzzles(session)
    assert puzzle.status is PuzzleStatus.REJECTED and puzzle.reject_reason == "not_unique"
    assert puzzle.solution == [] and puzzle.outcome is None
    assert list_puzzles(session, bob.user_id, PuzzleFilters()) == []


def test_only_tracked_accounts_get_puzzles(
    session: Session, scholars_source: StubSource, job_context: JobContext
) -> None:
    """Alice (White) made no mistakes; Bob (Black) isn't tracked here."""
    alice_user = create_user(session, "Alice")
    alice = link_account(session, alice_user, Platform.LICHESS, "alice_attacker")
    import_games(session, alice, scholars_source, FetchFilters())

    run_analysis(session, alice, job_context, depth=12)

    assert all_puzzles(session) == []


def test_list_filters(
    session: Session, bob: ChessAccount, scholars_game: Game, job_context: JobContext
) -> None:
    run_analysis(session, bob, job_context, depth=12)

    def count(**filters: object) -> int:
        return len(list_puzzles(session, bob.user_id, PuzzleFilters(**filters)))  # type: ignore[arg-type]

    assert count() == 1
    assert count(phase=Phase.OPENING, severity=Classification.BLUNDER) == 1
    assert count(outcome=PuzzleOutcome.EQUALIZE, account_id=bob.id) == 1
    assert count(phase=Phase.ENDGAME) == 0
    assert count(outcome=PuzzleOutcome.MATE) == 0
    assert list_puzzles(session, bob.user_id + 1, PuzzleFilters()) == []
    assert list_puzzles(session, bob.user_id, PuzzleFilters(), offset=1) == []


def test_motif_taggers_feed_puzzle_themes_and_the_weakness_report(
    session: Session,
    bob: ChessAccount,
    scholars_game: Game,
    job_context: JobContext,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Proves the extension point: a registered tagger needs no other wiring."""

    class AlwaysFork:
        name = "fork"

        def tags(self, board: object, played: object, best_line: object) -> set[str]:
            return {"fork"}

    monkeypatch.setattr(motifs, "REGISTRY", [AlwaysFork()])
    run_analysis(session, bob, job_context, depth=12)

    assert all_puzzles(session)[0].themes == ["fork"]
    report = build_weakness_report(session, bob.user_id, WeaknessFilters(), settings)
    assert report.by_motif == {"fork": 1}
