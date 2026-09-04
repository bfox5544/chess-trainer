# Chess Trainer

A backend that turns your own games into training material. It imports a
player's games from Lichess and Chess.com, analyzes every move with Stockfish,
reports where winning chances are being lost, and builds puzzles from the
player's own mistakes.

This is the MVP: ingestion, analysis, reports, puzzles, an HTTP API, and a
small web frontend to use it. Spaced repetition, tactical motif detection, and
rating-band baselines are planned and the design leaves room for them (see
[Designed for later](#designed-for-later)).

## Quick start

Requirements: Python 3.11+, [uv](https://docs.astral.sh/uv/), Docker, and a
Stockfish binary (`brew install stockfish`).

```bash
cp .env.example .env                 # set STOCKFISH_PATH if yours differs
docker compose up -d                 # Postgres on localhost:54329
uv sync
uv run alembic upgrade head

uv run uvicorn chess_trainer.api.app:app --reload    # app on :8000, API docs at /docs
uv run chess-trainer-worker                          # in a second terminal
```

Then open <http://localhost:8000>: create a user, link an account, import
games, and watch the analysis run. Or drive the API directly:

```bash
curl -X POST localhost:8000/users -H 'content-type: application/json' \
     -d '{"display_name": "Me"}'                                   # -> {"id": 1, ...}
curl -X POST localhost:8000/users/1/accounts -H 'content-type: application/json' \
     -d '{"platform": "lichess", "username": "your-name"}'         # -> {"id": 1, ...}
curl -X POST localhost:8000/accounts/1/import -H 'content-type: application/json' \
     -d '{"max_games": 20, "time_classes": ["blitz", "rapid"]}'    # -> {"job_id": 1}
curl localhost:8000/jobs/1               # import status, plus the analysis job it queued
curl localhost:8000/users/1/report       # weakness report
curl localhost:8000/users/1/puzzles      # puzzles from your mistakes
```

Tests and linting:

```bash
uv run pytest             # 201 tests; integration tests need `docker compose up -d`
uv run ruff check .
```

## API

| Method & path | Purpose |
|---|---|
| `GET /users` | List users (exists because there is no login yet) |
| `POST /users` | Create a user |
| `GET /users/{id}` | User and linked accounts |
| `POST /users/{id}/accounts` | Link a Lichess or Chess.com account |
| `POST /accounts/{id}/import` | Queue an import (and, by default, analysis). Returns `202 {job_id}` |
| `POST /accounts/{id}/analyze` | Queue (re-)analysis of stored games, optionally at a new depth |
| `GET /jobs/{id}` | Status, progress, result, and child jobs |
| `GET /accounts/{id}/games` | Stored games, newest first |
| `GET /users/{id}/games` | Games across all accounts with your color, result, and accuracy |
| `GET /games/{id}/analysis` | Game report: every move classified and explained, plus per-side totals |
| `GET /users/{id}/report` | Weakness report (`account_id`, `time_class`, `since` filters) |
| `GET /users/{id}/puzzles` | Puzzles (`outcome`, `phase`, `severity`, `account_id`, paging) |
| `GET /puzzles/{id}` | One puzzle: start position, side to move, full solution, and why the game move was a mistake |

Interactive docs are served at `/docs`.

## Frontend

A single-page app in `src/chess_trainer/web/`, served by the API at `/app`
(same origin, so no CORS setup).

| Page | What it does |
|---|---|
| Home | Accuracy and error rate, what to work on, recent games, next puzzle |
| Analysis | Game list; each game opens on a board with an eval bar, a winning-chances graph, classified moves, and the reasons each move was good or bad |
| Puzzles | Training hub with solved/unsolved tracking; solve by clicking or dragging |
| Stats | Move quality, accuracy by game, and errors by phase, clock, and opening |
| Import | Link accounts and import; progress shows as a banner on every page |

**Design system.** One stylesheet (`styles.css`) built on tokens: an ebony
surface scale, ivory for primary actions, blue for focus and selection, and a
slate-and-ivory board. Move quality has one colour and one symbol each
(best ★, inaccuracy ?!, mistake ?, blunder ??), defined once in `ui.js`
(`MOVE_KINDS`) and reused by the board badge, move list, charts, and tables.
Reusable pieces live in `ui.js` (buttons, panels, stat tiles, empty states,
dialogs), `board.js` (board, eval bar, thumbnails), and `charts.js`.

Decisions worth knowing:

- **No build step.** Plain HTML, CSS, and ES modules: no Node toolchain and
  nothing to install. The trade-off is no type checking or component
  framework; the code compensates with small modules and one `h()` helper.
- **Two vendored assets, no runtime dependencies:** chess.js (BSD-2-Clause)
  for move legality, and the "cburnett" piece set (BSD) that Lichess and
  Wikipedia use. Charts are hand-drawn SVG, so there is no charting library.
- **The board knows nothing about chess rules.** It draws a position, marks,
  arrows, and a badge, and reports the square picked. A press reports its
  square immediately and a drag reports the drop square, so click-to-move and
  drag-and-drop share one code path.
- **Accuracy is a simplified version of Lichess's:** the mean of a per-move
  score derived from win-probability loss. It will not match Lichess or
  Chess.com numbers exactly.
- **"What to work on" has minimum sample sizes** (`insights.js`), so a few
  unlucky moves are not reported as a weakness.
- **Puzzle solving history is stored in the browser**, because the backend
  does not record attempts yet. The UI says so, and clearing it asks first.
- **All text goes through `textContent`** (`dom.js`), so usernames and opening
  names from the platforms cannot inject markup.
- There is no login: the chosen profile is remembered in `localStorage`
  (`?user=ID` overrides it).

## Architecture

```
        HTTP                      jobs table (Postgres)
client ──────► FastAPI ──enqueue──► ┌────────────┐ ◄──claim── worker process
                 │                  │ queued jobs│              │
                 │ reads            └────────────┘              ├─ ingestion  (Lichess / Chess.com)
                 ▼                                              ├─ analysis   (Stockfish + eval cache)
        reports, puzzles ◄───────────── Postgres ◄──────────────┴─ puzzles
```

```
src/chess_trainer/
├── config.py        every tunable, from environment variables
├── db/              models, enums, session
├── accounts/        users and their platform accounts
├── ingestion/       GameSource protocol, Lichess + Chess.com clients, retrying HTTP, normalization
├── analysis/        winprob, classify, phase, clock, openings  (pure)
│                    engine, cache, replay, moves, pipeline     (I/O at the edges)
├── reports/         game report, weakness report, motif extension point
├── puzzles/         builder (pure), validators, generator, service
├── jobs/            queue, handlers, worker
├── api/             FastAPI app, routes, schemas
└── web/             static frontend served at /app (no build step)
```

The rule throughout: **chess logic is pure, I/O lives at the edges.** Move
classification, phase detection, win probability, and puzzle building are
plain functions with no database, engine, or network access, which is why they
can be tested with known positions and a scripted engine.

## Design decisions

### Background jobs: Postgres as the queue

The API inserts a row into `jobs`; a separate worker process claims rows with
`SELECT … FOR UPDATE SKIP LOCKED`, so several workers can run without ever
taking the same job. The status endpoint reads the same row.

- **Versus FastAPI `BackgroundTasks`:** those run inside the API process, are
  lost on restart, and compete with requests for CPU. Stockfish needs its own
  process.
- **Versus Celery / RQ:** both need a broker (Redis or RabbitMQ) and bring
  more moving parts. In return you get retries, scheduling, routing, and
  dashboards. None of that is needed yet, and throughput here is limited by
  Stockfish, not by a queue that polls once a second.
- **Upgrade path:** handlers are plain functions of `(session, job, context)`
  (`jobs/handlers.py`). Moving to Celery means new wrappers, not new logic.

Jobs are resumable: analysis commits per game and skips games already done, so
a crashed job (detected by a stale heartbeat) is simply re-queued.

### Mistakes are measured in win probability, not centipawns

Dropping from +8 to +5 loses three pawns of evaluation and almost no winning
chances; dropping from +1 to −2 changes the result of the game. Evaluations
are converted to win probability with the curve Lichess fitted to real games
(`analysis/winprob.py`), and a move is labeled by the points it gave away:
≥5 inaccuracy, ≥10 mistake, ≥15 blunder (configurable).

Edge cases, each covered by a test:

| Case | Handling |
|---|---|
| Point of view | Evals are stored from White's side; `win_pct()` is the only place that flips them |
| Forced mate | 100% / 0% regardless of length, so a slower mate is not an error |
| Mate already on the board | Scored from the rules; the engine is never asked |
| Played move is the engine's first choice | Loss is 0 (otherwise searching the two positions separately invents noise) |
| Position looks better after the move | Search noise; loss clamped to 0 |
| Only one legal move | Flagged `is_forced`, never an error, excluded from reports |
| Book moves | Flagged `in_book` but still classified (some named gambits are simply bad) |

### Game phases

A simplified version of Lichess's "Divider" (`analysis/phase.py`), based on
counting minor and major pieces (N, B, R, Q of both colors):

- **Endgame:** 6 or fewer remain.
- **Middlegame:** 10 or fewer remain, *or* either side has fewer than 4 pieces
  on its back rank (development is done), *or* 15 moves have been played.
- **Opening:** everything before that.

Phases only move forward. The ply where each phase starts is stored per game.

### Evaluation cache

Analysis is the expensive part, so no position is evaluated twice
(`analysis/cache.py`). A cached row answers a request only if:

1. it came from a **compatible engine config**,
2. at **at least the requested depth**,
3. with **at least the requested number of lines** (puzzles need two).

A row is only ever overwritten by a deeper search, enforced inside the upsert
so concurrent workers can't clobber each other.

- **Cache key:** `board.epd()` — pieces, side to move, castling, en passant —
  without move counters, so transpositions and different games share rows.
- **Engine fingerprint:** engine name and version (from the UCI handshake)
  plus options that change *what* is evaluated (a custom NNUE file).
  **Threads and hash size are deliberately excluded**: they change speed, not
  meaning, and including them would discard the whole cache whenever you tune
  performance. Upgrading Stockfish creates a new config, and games are
  re-analyzed with it on the next analyze job.
- **History-sensitive positions:** a repeated position, or one close to the
  50-move rule, can evaluate as a draw for reasons the key doesn't capture.
  These are analyzed with their move history and never cached. Everything else
  is analyzed from the bare position, so its row is valid in any game.
- **Mixed depths:** a deeper cached eval may sit next to a fresh shallower one
  for the same move. That is allowed (deeper is better) and both depths are
  stored on the move for auditing.

### Both sides' moves are analyzed and stored

Every position is evaluated anyway, so storing the opponent's moves costs no
engine time. Reports filter by the user's color. It also means a game between
two tracked accounts is stored and analyzed once.

### Puzzles need a real solution

Not every mistake is a puzzle. A candidate (a mistake or blunder that wasn't
forced) is accepted only if (`puzzles/builder.py`):

1. the best move beats the second-best by ≥15 win-% points, or is the only
   move that mates;
2. the solver ends up at least equal (≥50%) — "find the least-bad losing
   move" is not a fun puzzle;
3. the stored line is legal and ends on the solver's move.

The solution is then extended — opponent's best reply, solver's next move —
for as long as the solver's move stays unique, up to 10 plies. Each step
stores its evaluation and the runner-up move, so a puzzle can be re-validated
later without the engine.

Rejected candidates are kept with a reason (`not_unique`, `still_lost`, …), so
tuning the thresholds is a query, not a re-analysis.

**Honest limitation:** uniqueness is a *proxy* for "tactical". It filters out
positions with several good moves and most vague positional slips, but it
can't tell a quiet only-move from a combination. That is motif detection,
which is the next phase.

### Move explanations are built at read time from stored lines

Each move in a game report carries `explanation`: a list of reasons with a
stable `code` and a sentence (`analysis/explain.py`). Examples:

- "Puts the knight on g4 where it can be taken with Bxg4. Black wins a piece: 8...Bxg4 9. Bd2 Nge7."
- "Ignores the threat to the rook on e2: Rxe2 wins it."
- "Allows f4, forking the knight and the queen."
- "Misses Qxh5 (takes the undefended knight on h5), winning two pawns."
- "Misses a forced mate in 2: …" / "Allows White a forced mate in 1: 4. Qxf7#"

No extra engine work is needed. The analysis already stores the engine's best
line from every position, and the line from the position *after* a move
(how the opponent punishes it) is the next ply's `best_line`. Explanations
are therefore computed when a report is read, not stored. Every previously
analyzed game gets them, and improving the wording needs no migration or
re-analysis.

How a material claim is made:

1. Follow the punishing line (and the best line) for up to 8 plies and count
   material at the first *quiet* point: nobody in check, and the next move
   neither captures nor checks. Counting mid-exchange would report a queen as
   lost when it is about to be recaptured.
2. If the opponent just captured and this move (or the best move) takes back
   on that square, count from before their capture. A recapture restores
   balance; it doesn't "win" a piece.
3. Cross-check against the engine: a claim of N points needs the eval to have
   moved by at least 60·N centipawns. Line counting can stop mid-trade (a pawn
   taken now and won back three moves later, as in the Petrov); the eval
   can't be fooled that way.

"Hanging", "ignores the threat" and "stops defending" are only said when
they are literally true on the board. Otherwise the reason falls back to the
line and its net result. A mistake with no material or mate consequence is
called positional rather than given an invented tactic.

### One time-class formula for both platforms

Lichess and Chess.com draw the bullet/blitz/rapid lines differently. Every
game is classified with Lichess's formula (`base + 40 × increment`), so a
filter or report bucket means the same thing regardless of source.

### Opening names from one dataset

Lichess puts the opening in the PGN; Chess.com only gives a URL slug. Each
game is matched by position against the bundled Lichess openings dataset
(CC0, `data/openings.tsv`), so both platforms get identical names, and
`opening_ply` records where the player left theory. Rebuild the file with
`scripts/build_openings.py`.

### Time pressure scales with the time control

"Under 30 seconds" would label most of a 1-minute game as time pressure. The
threshold is `min(30s, 10% of base time)`, both configurable.

### Smaller choices

- **Sync SQLAlchemy and httpx.** The worker is bound by the engine and FastAPI
  runs sync routes in a thread pool; async would add complexity for no gain.
- **Enums stored as strings**, so adding a member is not a migration.
- **Weakness aggregation in Python.** One light row per move, grouped by pure
  functions. Simple to test; replaceable by SQL `GROUP BY` if it ever matters.
- **Variants and custom-start games are skipped at import**, with the reason
  counted in the job result. So are games shorter than 4 plies.
- **Imports don't auto-apply "since last sync".** A second import with a
  different time-class filter must still reach older games; the unique
  constraint makes re-fetching harmless. Pass `since` explicitly to narrow it.

## Data model

| Table | Purpose |
|---|---|
| `users` | A person. No auth yet |
| `chess_accounts` | A Lichess or Chess.com account, linked to a user |
| `games` | One row per game: PGN, players, time control, opening, phase boundaries, analysis depth |
| `account_games` | Which tracked account played which color |
| `engine_configs` | Engine identities whose evaluations are comparable |
| `position_evals` | The cache: (position, engine config, line count) → depth and lines |
| `move_analyses` | One row per move: evals, win %, classification, phase, clock |
| `puzzles` | Puzzle candidates with full solution, status, and provenance |
| `jobs` | Background jobs; also the queue |

Rows in `move_analyses` and `puzzles` are upserted by `(game_id, ply)`.
Re-analysis updates them in place, so ids stay stable for anything that will
reference them later.

## Testing

- **Unit tests** (`tests/unit`) cover the pure logic with known positions and
  the sample games in `tests/fixtures/pgn/`: win probability, classification,
  phases, openings, clocks, cache rules, puzzle building.
- **HTTP is mocked** with `respx`; no test touches the network.
- **The engine is faked** (`tests/fakes.py`) with scripted evaluations and a
  call log, which is how cache hits and misses are proven. One optional test
  runs real Stockfish and is skipped if the binary is missing.
- **Integration tests** run against a real Postgres test database, migrated
  with Alembic, each test inside a rolled-back transaction. SQLite is not used
  because the design depends on `ON CONFLICT`, `SKIP LOCKED`, and JSONB.

## Designed for later

Not built, but the current design was shaped so these fit without rework:

- **Tactical motifs.** `reports/motifs.py` defines a `MotifTagger` protocol
  and an empty registry. Puzzle generation already calls it and stores the
  result in `puzzles.themes`; the weakness report already groups by it. A test
  registers a dummy tagger to prove no further wiring is needed.
- **Puzzle attempts and spaced repetition.** A future `puzzle_attempts` table
  (`user_id`, `puzzle_id`, `attempted_at`, `solved`, `moves_played`,
  `time_ms`) hangs off stable puzzle ids and per-puzzle ownership, both of
  which exist now.
- **External puzzles.** `puzzles.source` distinguishes `own_game` from future
  imports such as the Lichess puzzle database.
- **Rating-band baselines.** Opponents' moves are already analyzed and phase,
  opening, and time-control metadata are stored per move and game.
- **Authentication.** Every user-scoped route resolves its user through one
  function, `api/deps.py: load_user`. That is the only place auth needs to go.

## Known limitations

- The frontend is checked by scripted browser runs, not by an automated test
  suite; the backend only tests that its files are served.
- Puzzle attempts are saved only in the browser, not on the server.
- Explanations cover material, forks and mates. They don't yet name pins,
  skewers, discovered attacks or trapped pieces (a trap shows up as "after the
  reply …, material can't be held"), and positional mistakes get a generic
  sentence.
- There is no light theme and no board/piece theme choice.
- A position with two different mating moves is rejected as "not unique",
  which loses some legitimate mate puzzles.
- Usernames are verified at import time, not when an account is linked; a typo
  shows up as a failed import job.
- A dropped connection in the middle of a Lichess stream fails the import job
  rather than resuming; re-running the import is safe.
