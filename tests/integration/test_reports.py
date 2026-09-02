from collections.abc import Callable
from datetime import UTC, datetime

import pytest
from sqlalchemy.orm import Session

from chess_trainer.accounts.service import link_account
from chess_trainer.analysis.cache import EvalCache, Evaluator, get_or_create_engine_config
from chess_trainer.analysis.classify import Thresholds
from chess_trainer.analysis.openings import load_opening_book
from chess_trainer.analysis.pipeline import analyze_game
from chess_trainer.config import Settings
from chess_trainer.db.enums import Platform, TimeClass
from chess_trainer.db.models import ChessAccount, Game, User
from chess_trainer.ingestion.service import import_games
from chess_trainer.ingestion.sources import FetchFilters, RawGame
from chess_trainer.reports.game_report import build_game_report
from chess_trainer.reports.weakness import WeaknessFilters, build_weakness_report
from tests.fakes import FakeEngine, StubSource

pytestmark = pytest.mark.integration


@pytest.fixture
def analyzed(
    session: Session,
    bob: ChessAccount,
    scholars_game: Game,
    engine: FakeEngine,
    load_pgn: Callable[[str], str],
) -> tuple[ChessAccount, ChessAccount]:
    """Bob with two accounts and one analyzed game on each.

    Lichess: Scholar's Mate as Black (one blunder). Chess.com: the Opera Game
    as White (the fake engine scores every move as fine).
    """
    user = session.get_one(User, bob.user_id)
    chesscom = link_account(session, user, Platform.CHESSCOM, "BobLearner")
    opera = RawGame(Platform.CHESSCOM, "opera", load_pgn("chesscom_opera_game"))
    import_games(session, chesscom, StubSource([opera], Platform.CHESSCOM), FetchFilters())
    config = get_or_create_engine_config(session, engine)
    evaluator = Evaluator(engine, EvalCache(session, config.id))
    for game in session.query(Game):
        analyze_game(session, game, evaluator, load_opening_book(), 12, Thresholds(), config.id)
    return bob, chesscom


def test_game_report_summarizes_each_side(
    session: Session, analyzed: tuple[ChessAccount, ChessAccount], scholars_game: Game
) -> None:
    report = build_game_report(session, scholars_game.id)
    assert report is not None
    assert len(report.moves) == 7
    assert (report.white.moves, report.white.blunders) == (4, 0)
    assert (report.black.moves, report.black.blunders) == (3, 1)
    assert report.black.errors_per_100_moves == pytest.approx(33.3)


def test_game_report_for_unknown_or_unanalyzed_game(session: Session, scholars_game: Game) -> None:
    assert build_game_report(session, 999_999) is None
    report = build_game_report(session, scholars_game.id)
    assert report is not None and report.moves == [] and report.white.moves == 0


def test_weakness_report_combines_all_of_a_users_accounts(
    session: Session, analyzed: tuple[ChessAccount, ChessAccount], settings: Settings
) -> None:
    bob, _ = analyzed
    report = build_weakness_report(session, bob.user_id, WeaknessFilters(), settings)

    assert report.games_analyzed == 2
    # Only Bob's own moves: 3 as Black in one game + 17 as White in the other.
    assert (report.overall.moves, report.overall.blunders) == (20, 1)
    phases = {b.key: b.stats for b in report.by_phase}
    assert [b.key for b in report.by_phase] == ["opening", "middlegame", "endgame"]
    assert (phases["opening"].moves, phases["opening"].blunders) == (12, 1)
    assert (phases["middlegame"].moves, phases["endgame"].moves) == (7, 1)
    openings = {b.key: b.stats for b in report.by_opening}
    assert openings["Bishop's Opening"].blunders == 1
    assert openings["Philidor Defense"].moves == 17
    assert [b.key for b in report.by_time_pressure] == ["not_under_pressure"]
    assert report.by_motif == {}


def test_weakness_report_filters(
    session: Session, analyzed: tuple[ChessAccount, ChessAccount], settings: Settings
) -> None:
    bob, chesscom = analyzed

    def moves(filters: WeaknessFilters) -> int:
        return build_weakness_report(session, bob.user_id, filters, settings).overall.moves

    assert moves(WeaknessFilters(account_id=chesscom.id)) == 17
    assert moves(WeaknessFilters(account_id=bob.id)) == 3
    assert moves(WeaknessFilters(time_class=TimeClass.BLITZ)) == 3
    assert moves(WeaknessFilters(since=datetime(2024, 3, 1, tzinfo=UTC))) == 3
    assert moves(WeaknessFilters(time_class=TimeClass.CLASSICAL)) == 0


def test_weakness_report_for_user_without_games(session: Session, settings: Settings) -> None:
    report = build_weakness_report(session, 424242, WeaknessFilters(), settings)
    assert report.games_analyzed == 0 and report.overall.moves == 0
    assert report.by_phase == [] and report.by_opening == []
