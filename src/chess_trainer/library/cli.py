"""Load the Lichess puzzle database from the command line:

    uv run chess-trainer-puzzle-library --limit 100000
    uv run chess-trainer-puzzle-library --source ~/Downloads/lichess_db_puzzle.csv.zst

The same import runs as a background job when started from the Puzzles page.
"""

import argparse
import sys

from chess_trainer.config import get_settings
from chess_trainer.db.session import get_sessionmaker
from chess_trainer.library.feed import open_lines
from chess_trainer.library.parse import RowFilter
from chess_trainer.library.store import import_library


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    settings = get_settings()
    parser = argparse.ArgumentParser(description="Load puzzles from the Lichess puzzle database.")
    parser.add_argument(
        "--source",
        default=settings.puzzle_library_source,
        help="URL or path of lichess_db_puzzle.csv(.zst) (default: the Lichess download)",
    )
    parser.add_argument("--limit", type=int, help="stop after storing this many puzzles")
    parser.add_argument(
        "--min-popularity", type=int, default=settings.puzzle_library_min_popularity
    )
    parser.add_argument("--min-plays", type=int, default=settings.puzzle_library_min_plays)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    settings = get_settings()

    def report(stored: int) -> None:
        print(f"\r{stored:,} puzzles stored", end="", file=sys.stderr, flush=True)

    with (
        get_sessionmaker()() as session,
        open_lines(
            args.source,
            user_agent=settings.http_user_agent,
            timeout=settings.http_timeout_seconds,
        ) as lines,
    ):
        result = import_library(
            session,
            lines,
            limit=args.limit,
            row_filter=RowFilter(args.min_popularity, args.min_plays),
            batch_size=settings.puzzle_library_batch_size,
            on_progress=report,
        )
    print(file=sys.stderr)
    print(
        f"Stored {result.stored:,} puzzles ({result.read:,} read, "
        f"{result.skipped_filtered:,} below the quality floor, "
        f"{result.skipped_malformed:,} malformed)."
    )


if __name__ == "__main__":
    main()
