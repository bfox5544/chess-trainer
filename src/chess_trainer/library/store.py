"""Load library puzzles into the database and query them."""

import random
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass

from sqlalchemy import delete, func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from chess_trainer.db.models import LibraryAttempt, LibraryPuzzle, LibraryTheme
from chess_trainer.library.parse import LibraryRow, RowFilter, parse_record, read_records

UPDATABLE = (
    "fen",
    "moves",
    "rating",
    "rating_deviation",
    "popularity",
    "nb_plays",
    "themes",
    "game_url",
    "opening_tags",
)


@dataclass(frozen=True)
class LibraryImportResult:
    read: int  # records read from the file
    stored: int  # inserted or updated
    skipped_malformed: int
    skipped_filtered: int

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def upsert_rows(session: Session, rows: list[LibraryRow]) -> None:
    """Insert or refresh rows by Lichess id. `random_key` is kept on update so
    a re-import does not reshuffle the library."""
    if not rows:
        return
    values = [
        {
            "id": row.id,
            "fen": row.fen,
            "moves": list(row.moves),
            "rating": row.rating,
            "rating_deviation": row.rating_deviation,
            "popularity": row.popularity,
            "nb_plays": row.nb_plays,
            "themes": list(row.themes),
            "game_url": row.game_url,
            "opening_tags": list(row.opening_tags),
        }
        for row in rows
    ]
    stmt = insert(LibraryPuzzle).values(values)
    stmt = stmt.on_conflict_do_update(
        index_elements=[LibraryPuzzle.id],
        set_={column: stmt.excluded[column] for column in UPDATABLE},
    )
    session.execute(stmt)


def import_library(
    session: Session,
    lines: Iterable[str],
    *,
    limit: int | None,
    row_filter: RowFilter,
    batch_size: int,
    on_progress: Callable[[int], None] | None = None,
) -> LibraryImportResult:
    """Store up to `limit` accepted puzzles from the CSV lines. Commits after
    each batch, so a dropped download keeps everything stored before it and
    re-running the import is safe (rows are upserted)."""
    read = stored = malformed = filtered = 0
    batch: list[LibraryRow] = []
    for record in read_records(lines):
        if limit is not None and stored + len(batch) >= limit:
            break
        read += 1
        row = parse_record(record)
        if row is None:
            malformed += 1
            continue
        if not row_filter.accepts(row):
            filtered += 1
            continue
        batch.append(row)
        if len(batch) >= batch_size:
            stored += flush(session, batch, on_progress, stored)
            batch = []
    stored += flush(session, batch, on_progress, stored)
    refresh_theme_counts(session)
    session.commit()
    return LibraryImportResult(read, stored, malformed, filtered)


def flush(
    session: Session,
    batch: list[LibraryRow],
    on_progress: Callable[[int], None] | None,
    stored_before: int,
) -> int:
    upsert_rows(session, batch)
    session.commit()
    if on_progress is not None:
        on_progress(stored_before + len(batch))
    return len(batch)


def refresh_theme_counts(session: Session) -> None:
    session.execute(delete(LibraryTheme))
    session.execute(
        text(
            "INSERT INTO library_themes (theme, count) "
            "SELECT theme, count(*) FROM library_puzzles, unnest(themes) AS theme "
            "GROUP BY theme"
        )
    )


# --- Queries -------------------------------------------------------------------


@dataclass(frozen=True)
class LibraryFilters:
    rating_min: int | None = None
    rating_max: int | None = None
    theme: str | None = None
    opening: str | None = None  # an opening tag, e.g. "Caro-Kann_Defense"
    unseen_by: int | None = None  # leave out puzzles this user has attempted


def library_size(session: Session) -> int:
    return session.scalar(select(func.count()).select_from(LibraryPuzzle)) or 0


def theme_counts(session: Session) -> list[LibraryTheme]:
    stmt = select(LibraryTheme).order_by(LibraryTheme.count.desc(), LibraryTheme.theme)
    return list(session.scalars(stmt))


def filter_conditions(filters: LibraryFilters, exclude: Iterable[str] = ()) -> list:  # type: ignore[type-arg]
    conditions = []
    if filters.rating_min is not None:
        conditions.append(LibraryPuzzle.rating >= filters.rating_min)
    if filters.rating_max is not None:
        conditions.append(LibraryPuzzle.rating <= filters.rating_max)
    if filters.theme:
        conditions.append(LibraryPuzzle.themes.contains([filters.theme]))
    if filters.opening:
        conditions.append(LibraryPuzzle.opening_tags.contains([filters.opening]))
    if filters.unseen_by is not None:
        attempted = select(LibraryAttempt.puzzle_id).where(
            LibraryAttempt.user_id == filters.unseen_by
        )
        conditions.append(LibraryPuzzle.id.not_in(attempted))
    excluded = list(exclude)
    if excluded:
        conditions.append(LibraryPuzzle.id.not_in(excluded))
    return conditions


def random_puzzles(
    session: Session,
    filters: LibraryFilters,
    count: int,
    exclude: Iterable[str] = (),
    draw: Callable[[], float] = random.random,
) -> list[LibraryPuzzle]:
    """Up to `count` random puzzles matching the filters.

    Takes consecutive rows on the indexed `random_key` from a random point,
    wrapping around once. Rows are not equally likely (a row after a large
    gap in keys is picked more often), which is fine for training and avoids
    sorting millions of rows as ORDER BY random() would.
    """
    point = draw()
    base = (
        select(LibraryPuzzle)
        .where(*filter_conditions(filters, exclude))
        .order_by(LibraryPuzzle.random_key)
    )
    found = list(session.scalars(base.where(LibraryPuzzle.random_key >= point).limit(count)))
    if len(found) < count:
        wrapped = base.where(LibraryPuzzle.random_key < point).limit(count - len(found))
        found += session.scalars(wrapped)
    return found


def random_puzzle(
    session: Session,
    filters: LibraryFilters,
    exclude: Iterable[str] = (),
    draw: Callable[[], float] = random.random,
) -> LibraryPuzzle | None:
    """One random puzzle matching the filters, or None if nothing matches."""
    found = random_puzzles(session, filters, 1, exclude, draw)
    return found[0] if found else None
