"""Rebuild src/chess_trainer/data/openings.tsv from the Lichess openings dataset.

Source: https://github.com/lichess-org/chess-openings (CC0). Download a.tsv ...
e.tsv into a directory, then:

    uv run python scripts/build_openings.py <directory-with-tsvs>

The upstream files list each opening as a move sequence. We store the resulting
position (EPD) instead, so the app can look openings up by position without
replaying 3,800 move lists at startup.
"""

import csv
import sys
from pathlib import Path

import chess

OUTPUT = Path(__file__).parent.parent / "src" / "chess_trainer" / "data" / "openings.tsv"


def epd_after(pgn_moves: str) -> str:
    board = chess.Board()
    for token in pgn_moves.split():
        if not token.endswith("."):  # skip move numbers like "12."
            board.push_san(token)
    return board.epd()


def main(source_dir: Path) -> None:
    rows: dict[str, tuple[str, str]] = {}
    for path in sorted(source_dir.glob("[a-e].tsv")):
        with path.open(newline="") as handle:
            for row in csv.DictReader(handle, delimiter="\t"):
                rows.setdefault(epd_after(row["pgn"]), (row["eco"], row["name"]))
    with OUTPUT.open("w", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(["eco", "name", "epd"])
        for epd, (eco, name) in sorted(rows.items(), key=lambda item: (item[1], item[0])):
            writer.writerow([eco, name, epd])
    print(f"wrote {len(rows)} openings to {OUTPUT}")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
