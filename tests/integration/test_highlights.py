import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from chess_trainer.analysis.cache import EvalCache, Evaluator, get_or_create_engine_config
from chess_trainer.analysis.classify import Thresholds
from chess_trainer.analysis.highlights import HIGHLIGHTS_VERSION, HighlightConfig
from chess_trainer.analysis.openings import load_opening_book
from chess_trainer.analysis.pipeline import analyze_game, mark_highlights
from chess_trainer.analysis.winprob import Eval
from chess_trainer.db.enums import Highlight, JobKind, JobStatus
from chess_trainer.db.models import ChessAccount, Game, MoveAnalysis
from chess_trainer.jobs import queue
from chess_trainer.jobs.handlers import JobContext
from chess_trainer.jobs.worker import work_once
from tests.fakes import FakeEngine, position_after

pytestmark = pytest.mark.integration


@pytest.fixture
def only_move(engine: FakeEngine) -> None:
    """After 1.e4 e5 2.Bc4, Bob's 2...Nc6 is the engine's choice and the
    second best (2...Nf6 in this script) is far worse for Black."""
    board = position_after("e4", "e5", "Bc4")
    engine.script[board.epd()] = [("b8c6", Eval(cp=0)), ("g8f6", Eval(cp=300))]


def evaluator_for(session: Session, engine: FakeEngine) -> Evaluator:
    config = get_or_create_engine_config(session, engine)
    return Evaluator(engine, EvalCache(session, config.id))


def analyze(session: Session, game: Game, engine: FakeEngine) -> None:
    config = get_or_create_engine_config(session, engine)
    evaluator = evaluator_for(session, engine)
    analyze_game(session, game, evaluator, load_opening_book(), 12, Thresholds(), config.id)


def move_at(session: Session, game: Game, ply: int) -> MoveAnalysis:
    stmt = select(MoveAnalysis).where(MoveAnalysis.game_id == game.id, MoveAnalysis.ply == ply)
    return session.scalars(stmt).one()


@pytest.mark.usefixtures("only_move")
def test_the_only_good_move_is_marked_great(
    session: Session, scholars_game: Game, engine: FakeEngine
) -> None:
    analyze(session, scholars_game, engine)
    before = len(engine.calls)
    marked = mark_highlights(
        session, scholars_game, evaluator_for(session, engine), HighlightConfig(), 12
    )

    assert marked == 1 and scholars_game.highlights_version == HIGHLIGHTS_VERSION
    great = move_at(session, scholars_game, 3)
    assert (great.san, great.highlight) == ("Nc6", Highlight.GREAT)
    assert great.second_best_san == "Nf6" and great.second_best_win_pct is not None
    assert great.second_best_win_pct < 30
    # White's moves are not checked; e5 is book; Nf6 was a blunder. Only Nc6
    # needed a second line.
    assert [call[2] for call in engine.calls[before:]] == [2]


@pytest.mark.usefixtures("only_move")
def test_games_analyzed_before_the_check_are_checked_by_the_next_job(
    session: Session,
    scholars_game: Game,
    bob: ChessAccount,
    engine: FakeEngine,
    job_context: JobContext,
) -> None:
    analyze(session, scholars_game, engine)
    assert scholars_game.highlights_version is None

    job = queue.enqueue(session, JobKind.ANALYZE, {"account_id": bob.id, "depth": 12})
    assert work_once(session, job_context)
    assert job.status is JobStatus.SUCCEEDED and job.result is not None
    assert job.result["analyzed"] == 0
    assert (job.result["checked_for_highlights"], job.result["highlights"]) == (1, 1)
    assert scholars_game.highlights_version == HIGHLIGHTS_VERSION


@pytest.mark.usefixtures("only_move")
def test_highlights_endpoint_and_game_report(
    client: TestClient, session: Session, scholars_game: Game, bob: ChessAccount, engine: FakeEngine
) -> None:
    analyze(session, scholars_game, engine)
    url = f"/users/{bob.user_id}/highlights"
    assert client.get(url).json() == {"great": 0, "brilliant": 0, "unchecked_games": 1, "moves": []}

    mark_highlights(session, scholars_game, evaluator_for(session, engine), HighlightConfig(), 12)
    body = client.get(url).json()
    assert (body["great"], body["brilliant"], body["unchecked_games"]) == (1, 0, 0)
    (move,) = body["moves"]
    assert (move["game"]["id"], move["ply"], move["san"], move["kind"]) == (
        scholars_game.id,
        3,
        "Nc6",
        "great",
    )
    assert move["explanation"].startswith("The only good move: the next best, Nf6,")
    assert client.get(url, params={"kind": "brilliant"}).json()["moves"] == []

    report = client.get(f"/games/{scholars_game.id}/analysis").json()
    nc6 = report["moves"][3]
    assert nc6["highlight"] == "great" and nc6["second_best_san"] == "Nf6"
    assert nc6["explanation"][0]["code"] == "great"
