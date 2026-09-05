"""Loading the puzzle library into Postgres, querying it, and its API."""

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import IO

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from chess_trainer.db.models import LibraryPuzzle
from chess_trainer.jobs.handlers import JobContext
from chess_trainer.jobs.worker import work_once
from chess_trainer.library.parse import RowFilter
from chess_trainer.library.store import (
    LibraryFilters,
    import_library,
    library_size,
    random_puzzle,
    theme_counts,
)

pytestmark = pytest.mark.integration

FIXTURE = Path(__file__).parent.parent / "fixtures" / "library" / "lichess_db_puzzle.csv"


def load(session: Session, limit: int | None = None, batch_size: int = 2):  # type: ignore[no-untyped-def]
    with FIXTURE.open() as lines:
        return import_library(
            session, lines, limit=limit, row_filter=RowFilter(50, 50), batch_size=batch_size
        )


def test_import_stores_accepted_rows_and_counts_themes(session: Session) -> None:
    progress: list[int] = []
    with FIXTURE.open() as lines:
        result = import_library(
            session,
            lines,
            limit=None,
            row_filter=RowFilter(50, 50),
            batch_size=2,
            on_progress=progress.append,
        )
    assert (result.read, result.stored) == (7, 5)
    assert (result.skipped_filtered, result.skipped_malformed) == (1, 1)
    assert progress == [2, 4, 5]
    assert library_size(session) == 5
    counts = {t.theme: t.count for t in theme_counts(session)}
    assert counts["advantage"] == 3 and counts["mateIn1"] == 1
    assert "promotion" not in counts  # only on the filtered-out puzzle


def test_import_stops_at_the_limit(session: Session) -> None:
    assert load(session, limit=3).stored == 3
    assert library_size(session) == 3


def test_reimport_updates_in_place_and_keeps_the_shuffle(session: Session) -> None:
    load(session)
    before = {p.id: p.random_key for p in session.query(LibraryPuzzle)}
    session.query(LibraryPuzzle).filter_by(id="00008").update({"rating": 1})
    load(session)
    session.expire_all()
    after = {p.id: p.random_key for p in session.query(LibraryPuzzle)}
    assert after == before
    assert session.get_one(LibraryPuzzle, "00008").rating == 1819


def test_random_puzzle_respects_filters_and_wraps_around(session: Session) -> None:
    load(session)
    mates = random_puzzle(session, LibraryFilters(theme="mateIn1"))
    assert mates is not None and mates.id == "0000H"
    easy = random_puzzle(session, LibraryFilters(rating_max=1100), draw=lambda: 0.0)
    assert easy is not None and easy.rating <= 1100
    # A draw past every key wraps to the start instead of finding nothing.
    assert random_puzzle(session, LibraryFilters(), draw=lambda: 1.0) is not None
    assert random_puzzle(session, LibraryFilters(theme="mateIn1"), exclude=["0000H"]) is None
    assert random_puzzle(session, LibraryFilters(rating_min=3000)) is None


# --- API -------------------------------------------------------------------------


def test_library_api(client: TestClient, session: Session) -> None:
    assert client.get("/library").json() == {"total": 0, "themes": []}
    assert client.get("/library/puzzles/random").status_code == 404
    load(session)

    summary = client.get("/library").json()
    assert summary["total"] == 5
    assert {"theme": "mateIn1", "count": 1} in summary["themes"]

    puzzle = client.get("/library/puzzles/random", params={"theme": "mateIn1"}).json()
    assert puzzle["id"] == "0000H"
    assert puzzle["setup"] == {"uci": "d1h5", "san": "Qxh5", "by": "opponent"}
    assert puzzle["user_color"] == "black"
    assert puzzle["solution"] == [{"uci": "d5g2", "san": "Qg2#", "by": "user"}]
    assert client.get("/library/puzzles/0000H").json() == puzzle
    assert client.get("/library/puzzles/nope").status_code == 404
    sample = client.get("/library/puzzles", params={"limit": 3}).json()
    assert len(sample) == 3 and len({p["id"] for p in sample}) == 3
    everything = client.get("/library/puzzles", params={"limit": 50}).json()
    assert len(everything) == 5  # wraps around to collect every match once
    assert client.get("/library/puzzles", params={"theme": "nope"}).json() == []
    params = {"rating_min": 1000, "rating_max": 1100}
    assert client.get("/library/puzzles/random", params=params).json()["rating"] <= 1100


@contextmanager
def fixture_feed() -> Iterator[IO[str]]:
    with FIXTURE.open() as lines:
        yield lines


def test_import_job(client: TestClient, session: Session, job_context: JobContext) -> None:
    job_context.open_puzzle_library = fixture_feed
    job_id = client.post("/library/import", json={"limit": 4}).json()["job_id"]
    # A second request while the first is pending returns the same job.
    assert client.post("/library/import", json={}).json()["job_id"] == job_id
    assert work_once(session, job_context)
    job = client.get(f"/jobs/{job_id}").json()
    assert job["status"] == "succeeded"
    assert job["result"]["stored"] == 4
    assert (job["progress_done"], job["progress_total"]) == (4, 4)
    assert client.get("/library").json()["total"] == 4
