"""Parsing, presenting and streaming the Lichess puzzle database."""

from pathlib import Path

import httpx
import pytest
import respx
import zstandard

from chess_trainer.db.enums import Color
from chess_trainer.ingestion.errors import SourceUnavailable
from chess_trainer.library.feed import open_lines
from chess_trainer.library.parse import RowFilter, parse_record, read_records
from chess_trainer.library.present import trainer_line

FIXTURE = Path(__file__).parent.parent / "fixtures" / "library" / "lichess_db_puzzle.csv"
URL = "https://database.example/lichess_db_puzzle.csv.zst"


def fixture_lines() -> list[str]:
    return FIXTURE.read_text().splitlines(keepends=True)


def test_rows_parse_with_a_header() -> None:
    rows = [parse_record(record) for record in read_records(fixture_lines())]
    assert [row.id if row else None for row in rows] == [
        "00008", "0000D", "0000H", "0008Q", "0009B", "004b0", None,
    ]  # fmt: skip
    first = rows[0]
    assert first is not None
    assert first.moves[:2] == ("f2g3", "e6e7")
    assert first.themes == ("crushing", "hangingPiece", "long", "middlegame")
    assert first.rating == 1819 and first.popularity == 95 and first.nb_plays == 10446
    assert rows[2] is not None
    assert rows[2].opening_tags == ("French_Defense", "French_Defense_Tarrasch_Variation")


def test_rows_parse_without_a_header() -> None:
    """Older dumps had no header row and no DailyDate column."""
    legacy = [",".join(line.split(",")[:10]) + "\n" for line in fixture_lines()[1:3]]
    rows = [parse_record(record) for record in read_records(legacy)]
    assert [row.id for row in rows if row] == ["00008", "0000D"]


@pytest.mark.parametrize(
    "change",
    [
        {"Moves": "e2e4"},  # no reply to the setup move
        {"Moves": "e2e4 nonsense"},
        {"Rating": "high"},
        {"FEN": "8/8/8 w"},
        {"PuzzleId": "bad id!"},
    ],
)
def test_malformed_records_are_rejected(change: dict[str, str]) -> None:
    record = next(iter(read_records(fixture_lines())))
    assert parse_record(record) is not None
    assert parse_record({**record, **change}) is None


def test_quality_filter() -> None:
    rows = [parse_record(record) for record in read_records(fixture_lines())]
    accepted = [row.id for row in rows if row and RowFilter(50, 50).accepts(row)]
    assert accepted == ["00008", "0000D", "0000H", "0008Q", "0009B"]


def test_trainer_line_plays_the_setup_move_for_the_opponent() -> None:
    line = trainer_line(
        "r6k/pp2r2p/4Rp1Q/3p4/8/1N1P2R1/PqP2bPP/7K b - - 0 24",
        ["f2g3", "e6e7", "b2b1", "b3c1", "b1c1", "h6c1"],
    )
    assert line.setup.san == "Bxg3" and line.setup.by == "opponent"
    assert line.user_color is Color.WHITE
    assert line.start_fen.startswith("r6k/pp2r2p/4Rp1Q/3p4/8/1N1P2b1/PqP3PP/7K w")
    assert [(s.san, s.by) for s in line.solution] == [
        ("Rxe7", "user"),
        ("Qb1+", "opponent"),
        ("Nc1", "user"),
        ("Qxc1+", "opponent"),
        ("Qxc1", "user"),
    ]


def test_trainer_line_rejects_illegal_moves() -> None:
    with pytest.raises(ValueError, match="illegal move"):
        trainer_line("r6k/pp2r2p/4Rp1Q/3p4/8/1N1P2R1/PqP2bPP/7K b - - 0 24", ["f2g3", "e1e2"])


def test_feed_reads_plain_and_compressed_files(tmp_path: Path) -> None:
    compressed = tmp_path / "puzzles.csv.zst"
    compressed.write_bytes(zstandard.ZstdCompressor().compress(FIXTURE.read_bytes()))
    with open_lines(str(FIXTURE)) as plain, open_lines(str(compressed)) as unpacked:
        assert list(plain) == list(unpacked) == fixture_lines()


@respx.mock
def test_feed_streams_a_compressed_download() -> None:
    body = zstandard.ZstdCompressor().compress(FIXTURE.read_bytes())
    respx.get(URL).mock(return_value=httpx.Response(200, content=body))
    with open_lines(URL) as lines:
        assert next(iter(lines)).startswith("PuzzleId,FEN")


@respx.mock
def test_feed_download_failure_is_reported_as_unavailable() -> None:
    respx.get(URL).mock(return_value=httpx.Response(503))
    with pytest.raises(SourceUnavailable), open_lines(URL):
        pass
