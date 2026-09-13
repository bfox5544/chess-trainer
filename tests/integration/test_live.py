"""Scoring a move live ("keep playing"), with the scripted engine."""

from fastapi.testclient import TestClient

from chess_trainer.api.deps import SharedEngine, get_shared_engine
from tests.fakes import FakeEngine

BEFORE_NF6 = "r1bqkbnr/pppp1ppp/2n5/4p2Q/2B1P3/8/PPPP1PPP/RNB1K1NR b KQkq - 3 3"
BARE_KINGS = "8/8/8/8/8/8/8/K6k w - - 0 1"


def score(client: TestClient, fen: str, uci: str):  # type: ignore[no-untyped-def]
    return client.post("/analysis/move", json={"fen": fen, "uci": uci})


def test_a_move_is_scored_like_a_game_move(client: TestClient, engine: FakeEngine) -> None:
    body = score(client, BEFORE_NF6, "g8f6").json()
    # The same verdict the analysis of the Scholar's Mate game stores.
    assert (body["san"], body["classification"], body["is_best"]) == ("Nf6", "blunder", False)
    assert body["best_move_san"] == "g6" and body["win_pct_loss"] > 15
    assert (body["color"], body["move_number"]) == ("black", 3)
    assert [reason["code"] for reason in body["explanation"]] == ["allows_mate"]
    assert body["reply"]["san"] == "Qxf7#"

    best = score(client, BEFORE_NF6, "g7g6").json()
    assert (best["classification"], best["is_best"], best["win_pct_loss"]) == ("good", True, 0)
    assert best["reply"] is not None


def test_evaluations_are_cached(client: TestClient, engine: FakeEngine) -> None:
    score(client, BEFORE_NF6, "g8f6")
    calls = len(engine.calls)
    assert calls == 2  # the position before and the position after
    score(client, BEFORE_NF6, "g8f6")
    assert len(engine.calls) == calls


def test_checkmate_ends_the_game(client: TestClient) -> None:
    after_nf6 = score(client, BEFORE_NF6, "g8f6").json()["fen_after"]
    mate = score(client, after_nf6, "h5f7").json()
    assert (mate["san"], mate["is_best"], mate["reply"]) == ("Qxf7#", True, None)


def test_engine_reply(client: TestClient) -> None:
    reply = client.post("/analysis/reply", json={"fen": BEFORE_NF6}).json()
    assert reply["move"]["san"] == "g6"
    assert client.post("/analysis/reply", json={"fen": BARE_KINGS}).json() == {"move": None}


def test_bad_input_is_rejected(client: TestClient) -> None:
    assert score(client, BEFORE_NF6, "g8g6").status_code == 422  # not a legal move
    assert score(client, "not a fen", "e2e4").status_code == 422
    assert score(client, BEFORE_NF6, "castle").status_code == 422
    assert (
        client.post("/analysis/reply", json={"fen": "8/8/8/8/8/8/8/8 w - - 0 1"}).status_code == 422
    )


def test_missing_engine_is_a_503(client: TestClient) -> None:
    def no_engine() -> FakeEngine:
        raise FileNotFoundError("stockfish")

    client.app.dependency_overrides[get_shared_engine] = lambda: SharedEngine(no_engine)  # type: ignore[attr-defined]
    assert score(client, BEFORE_NF6, "g8f6").status_code == 503
