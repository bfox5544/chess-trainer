"""The HTTP API end to end: real routes and database, fake engine and source."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from chess_trainer.api.app import create_app
from chess_trainer.api.deps import get_session
from chess_trainer.config import Settings, get_settings
from chess_trainer.jobs.handlers import JobContext
from chess_trainer.jobs.worker import work_once

pytestmark = pytest.mark.integration


@pytest.fixture
def client(session: Session, settings: Settings) -> Iterator[TestClient]:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_settings] = lambda: settings
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def user_id(client: TestClient) -> int:
    return client.post("/users", json={"display_name": "Bob"}).json()["id"]


@pytest.fixture
def account_id(client: TestClient, user_id: int) -> int:
    body = {"platform": "lichess", "username": "BobLearner"}
    return client.post(f"/users/{user_id}/accounts", json=body).json()["id"]


@pytest.fixture
def analyzed(client: TestClient, account_id: int, session: Session, job_context: JobContext) -> int:
    """Import and analyze Bob's games by running the queued jobs. Returns the import job id."""
    job_id = client.post(f"/accounts/{account_id}/import", json={"depth": 12}).json()["job_id"]
    assert work_once(session, job_context)  # import
    assert work_once(session, job_context)  # analysis
    return job_id


def test_health(client: TestClient) -> None:
    assert client.get("/health").json() == {"status": "ok"}


def test_create_user_and_link_accounts(client: TestClient, user_id: int) -> None:
    lichess = client.post(
        f"/users/{user_id}/accounts", json={"platform": "lichess", "username": "BobLearner"}
    )
    chesscom = client.post(
        f"/users/{user_id}/accounts", json={"platform": "chesscom", "username": "BobLearner"}
    )
    assert lichess.status_code == chesscom.status_code == 201
    assert lichess.json()["username"] == "boblearner"

    user = client.get(f"/users/{user_id}").json()
    assert user["display_name"] == "Bob"
    assert [a["platform"] for a in user["accounts"]] == ["lichess", "chesscom"]


def test_linking_an_account_twice_conflicts(
    client: TestClient, user_id: int, account_id: int
) -> None:
    response = client.post(
        f"/users/{user_id}/accounts", json={"platform": "lichess", "username": "boblearner"}
    )
    assert response.status_code == 409


def test_unknown_resources_are_404(client: TestClient) -> None:
    assert client.get("/users/999999").status_code == 404
    assert client.post("/accounts/999999/import", json={}).status_code == 404
    assert client.get("/jobs/999999").status_code == 404
    assert client.get("/games/999999/analysis").status_code == 404
    assert client.get("/puzzles/999999").status_code == 404
    assert client.get("/users/999999/report").status_code == 404


def test_invalid_input_is_rejected(client: TestClient, user_id: int, account_id: int) -> None:
    assert client.post("/users", json={"display_name": ""}).status_code == 422
    bad_platform = {"platform": "chess24", "username": "x"}
    assert client.post(f"/users/{user_id}/accounts", json=bad_platform).status_code == 422
    assert client.post(f"/accounts/{account_id}/import", json={"max_games": 0}).status_code == 422
    bad_class = {"time_classes": ["hyperbullet"]}
    assert client.post(f"/accounts/{account_id}/import", json=bad_class).status_code == 422
    assert client.get(f"/users/{user_id}/puzzles?limit=1000").status_code == 422


def test_import_is_accepted_as_a_queued_job(client: TestClient, account_id: int) -> None:
    body = {"time_classes": ["blitz", "rapid"], "max_games": 25}
    response = client.post(f"/accounts/{account_id}/import", json=body)
    assert response.status_code == 202

    job = client.get(f"/jobs/{response.json()['job_id']}").json()
    assert (job["kind"], job["status"]) == ("import", "queued")
    assert job["params"]["time_classes"] == ["blitz", "rapid"]
    assert job["params"]["max_games"] == 25
    assert job["children"] == []


def test_job_status_shows_the_import_and_its_analysis(client: TestClient, analyzed: int) -> None:
    job = client.get(f"/jobs/{analyzed}").json()
    assert job["status"] == "succeeded"
    assert job["result"]["stored"] == 1
    (child,) = job["children"]
    assert (child["kind"], child["status"]) == ("analyze", "succeeded")
    assert (child["progress_done"], child["progress_total"]) == (1, 1)
    assert child["result"]["puzzles_created"] == 1


def test_games_and_game_report(client: TestClient, account_id: int, analyzed: int) -> None:
    (game,) = client.get(f"/accounts/{account_id}/games").json()
    assert game["opening_name"] == "Bishop's Opening" and game["analyzed_depth"] == 12

    report = client.get(f"/games/{game['id']}/analysis").json()
    assert report["game"]["id"] == game["id"]
    assert len(report["moves"]) == 7
    assert report["black"]["blunders"] == 1 and report["white"]["blunders"] == 0
    blunder = report["moves"][5]
    assert (blunder["san"], blunder["classification"], blunder["best_move_san"]) == (
        "Nf6",
        "blunder",
        "g6",
    )


def test_weakness_report(client: TestClient, user_id: int, analyzed: int) -> None:
    report = client.get(f"/users/{user_id}/report").json()
    assert report["games_analyzed"] == 1
    assert report["overall"]["blunders"] == 1
    assert report["by_phase"][0]["key"] == "opening"
    assert report["by_opening"][0]["key"] == "Bishop's Opening"
    assert report["by_motif"] == {}

    filtered = client.get(f"/users/{user_id}/report?time_class=classical").json()
    assert filtered["games_analyzed"] == 0


def test_puzzles_are_listed_and_fetchable(client: TestClient, user_id: int, analyzed: int) -> None:
    (listed,) = client.get(f"/users/{user_id}/puzzles").json()
    assert listed["played_san"] == "Nf6" and listed["user_color"] == "black"
    assert [step["san"] for step in listed["solution"]] == ["g6"]

    fetched = client.get(f"/puzzles/{listed['id']}").json()
    assert fetched == listed
    assert client.get(f"/users/{user_id}/puzzles?phase=endgame").json() == []


def test_analyze_endpoint_queues_a_job(client: TestClient, account_id: int) -> None:
    response = client.post(f"/accounts/{account_id}/analyze", json={"depth": 20})
    assert response.status_code == 202
    job = client.get(f"/jobs/{response.json()['job_id']}").json()
    assert (job["kind"], job["params"]["depth"]) == ("analyze", 20)
