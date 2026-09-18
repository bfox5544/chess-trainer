// Training hub. Three sources: puzzles made from your own mistakes, Lichess
// puzzles picked for you (views/recommended.js), and the Lichess puzzle
// database browsed by difficulty and theme.

import { api } from "../api.js";
import { miniBoard } from "../board.js";
import { append, clear, h, plural, titleCase } from "../dom.js";
import { clearHistory, isSolved, loadHistory } from "../history.js";
import { jobs } from "../jobs.js";
import { button, chip, confirmDialog, emptyState, loading, notice, pageHeader, segmented, select, statTile, themeLabel } from "../ui.js";
import { libraryCard } from "./library-card.js";
import { LIBRARY_PREFIX, filterQuery, openRandomLibraryPuzzle } from "./library-puzzle.js";
import { renderRecommendedHub } from "./recommended.js";

const PHASES = [["", "All"], ["opening", "Opening"], ["middlegame", "Middlegame"], ["endgame", "Endgame"]];

const SOURCES = [["mine", "From your games"], ["foryou", "For you"], ["lichess", "Lichess database"]];

function sourceSwitch(current) {
  return h(
    "div",
    { class: "source-switch" },
    segmented(SOURCES, current, (value) => (location.hash = value === "mine" ? "#/puzzles" : `#/puzzles?source=${value}`), "Puzzle source"),
  );
}

export async function renderPuzzles(container, context) {
  if (context.query.source === "lichess") return renderLibraryHub(container, context);
  if (context.query.source === "foryou") return renderRecommendedHub(container, context, sourceSwitch("foryou"));
  const user = context.user;
  const puzzles = await api.puzzles(user.id);
  if (!puzzles.length) {
    append(
      container,
      pageHeader("Puzzles", "Positions from your own games where you went wrong."),
      sourceSwitch("mine"),
      emptyState({
        iconName: "puzzle",
        title: "No puzzles from your games yet",
        text: "A puzzle is created when you make a mistake in a position that had one clearly best move. Import and analyze more games to get some, or practise with rated puzzles from Lichess meanwhile.",
        action: h(
          "div",
          { class: "empty-actions" },
          button("Import games", { variant: "primary", icon: "import", href: "#/import" }),
          button("Puzzles for you", { icon: "puzzle", href: "#/puzzles?source=foryou" }),
        ),
      }),
    );
    return;
  }

  let history = loadHistory(user.id);
  let phase = PHASES.some(([value]) => value === context.query.phase) ? context.query.phase : "";
  // Open on what is left to do; solved puzzles are one click away.
  let status = "unsolved";
  const summary = h("div", { class: "stat-row" });
  const grid = h("div", { class: "puzzle-grid" });
  const startSlot = h("span");
  const statusSlot = h("span");
  const setStatus = (value) => {
    status = value;
    render();
  };

  const render = () => {
    const solved = puzzles.filter((p) => isSolved(history, p.id));
    const firstTry = puzzles.filter((p) => history[p.id]?.firstTry).length;
    const next = puzzles.find((p) => !isSolved(history, p.id)) || puzzles[0];
    clear(startSlot).append(
      button(solved.length === puzzles.length ? "Replay from the start" : solved.length ? "Continue training" : "Start training", {
        variant: "primary",
        icon: "puzzle",
        href: `#/puzzles/${next.id}`,
      }),
    );
    clear(summary);
    append(
      summary,
      statTile("Puzzles", puzzles.length, "From your own mistakes"),
      statTile("Solved", `${solved.length} of ${puzzles.length}`),
      statTile("First try", solved.length ? `${Math.round((100 * firstTry) / solved.length)}%` : "—", "Of the puzzles you've solved"),
    );
    const visible = puzzles.filter(
      (p) => (!phase || p.phase === phase) && (!status || (status === "solved") === isSolved(history, p.id)),
    );
    const statuses = [
      ["unsolved", `Unsolved (${puzzles.length - solved.length})`],
      ["solved", `Solved (${solved.length})`],
      ["", "All"],
    ];
    const hadFocus = statusSlot.contains(document.activeElement);
    clear(statusSlot).append(segmented(statuses, status, setStatus, "Status"));
    if (hadFocus) statusSlot.querySelector('[aria-pressed="true"]')?.focus();
    clear(grid);
    if (!visible.length) {
      const allDone = status === "unsolved" && solved.length === puzzles.length;
      const text = allDone
        ? "You've solved every puzzle from your games. "
        : status === "solved" && !solved.length
          ? "No solved puzzles yet. Solve one and it moves here."
          : "No puzzles match these filters. ";
      append(
        grid,
        h(
          "p",
          { class: "muted grid-empty" },
          text,
          status === "unsolved" && solved.length
            ? h("button", { class: "link", type: "button", onclick: () => setStatus("solved") }, "Show solved puzzles")
            : null,
        ),
      );
      return;
    }
    append(grid, visible.map((puzzle) => puzzleCard(puzzle, history[puzzle.id])));
  };

  append(
    container,
    pageHeader("Puzzles", "Positions from your own games where you went wrong. Find the move you missed.", startSlot),
    sourceSwitch("mine"),
    summary,
    h(
      "div",
      { class: "toolbar" },
      segmented(PHASES, phase, (value) => { phase = value; render(); }, "Game phase"),
      statusSlot,
    ),
    grid,
    h(
      "p",
      { class: "muted small footnote" },
      "Solving history is kept in this browser only. ",
      h(
        "button",
        {
          class: "link",
          type: "button",
          onclick: async () => {
            const confirmed = await confirmDialog({
              title: "Clear solving history?",
              text: "Every puzzle will be marked unsolved again. This can't be undone.",
              confirmLabel: "Clear history",
            });
            if (!confirmed) return;
            clearHistory(user.id);
            history = {};
            render();
          },
        },
        "Clear history",
      ),
    ),
  );
  render();
}

function puzzleCard(puzzle, entry) {
  const userMoves = Math.ceil(puzzle.solution_plies / 2);
  return h(
    "a",
    { class: `puzzle-card${entry?.solved ? " solved" : ""}`, href: `#/puzzles/${puzzle.id}` },
    h("div", { class: "puzzle-thumb" }, miniBoard(puzzle.fen, puzzle.user_color), entry?.solved ? h("span", { class: "solved-mark" }, "Solved") : null),
    h(
      "div",
      { class: "puzzle-card-body" },
      h("div", { class: "puzzle-card-title" }, h("span", { class: `color-dot ${puzzle.user_color}` }), `${titleCase(puzzle.user_color)} to move`),
      h("div", { class: "muted small" }, `${plural(userMoves, "move")} to find · ${titleCase(puzzle.phase)}`),
      h("div", { class: "chips" }, chip(`Your ${puzzle.severity}`, puzzle.severity), puzzle.themes.map((theme) => chip(themeLabel(theme)))),
    ),
  );
}

// --- Lichess puzzle database ---------------------------------------------------

const DIFFICULTIES = [["easier", "Easier"], ["normal", "Normal"], ["harder", "Harder"], ["any", "Any rating"]];
const DIFFICULTY_OFFSET = { easier: -300, normal: 0, harder: 300 };
const RATING_WINDOW = 100;
const PREFS_KEY = "chessTrainer.libraryPrefs";
// Sizes offered for loading. ~62 bytes of compressed download per puzzle read.
const SIZES = [["10000", "10,000"], ["100000", "100,000"], ["500000", "500,000"], ["all", "Everything"]];
const BYTES_PER_PUZZLE = 62;

function loadPrefs() {
  try {
    return JSON.parse(localStorage.getItem(PREFS_KEY) || "{}");
  } catch {
    return {};
  }
}

function savePrefs(prefs) {
  try {
    localStorage.setItem(PREFS_KEY, JSON.stringify(prefs));
  } catch {
    /* storage unavailable */
  }
}

function ratingWindow(difficulty, level) {
  if (difficulty === "any") return { rating_min: null, rating_max: null };
  const center = Math.max(400 + RATING_WINDOW, level + DIFFICULTY_OFFSET[difficulty]);
  return { rating_min: center - RATING_WINDOW, rating_max: center + RATING_WINDOW };
}

function sizeHint(size) {
  if (size === "all") return "About 5 million puzzles: a 310 MB download, a few GB of disk, and several minutes.";
  const megabytes = Math.max(1, Math.round((Number(size) * BYTES_PER_PUZZLE * 1.25) / 1e6));
  return `About ${megabytes} MB to download.`;
}

/** Choose how many puzzles to load and queue the import job. */
function libraryLoader({ loaded }) {
  const sizes = SIZES.filter(([value]) => value === "all" || Number(value) > loaded);
  let size = sizes[Math.min(1, sizes.length - 1)][0];
  const hint = h("p", { class: "muted small" }, sizeHint(size));
  const status = h("div");
  const load = button(loaded ? "Load more puzzles" : "Load puzzles", {
    variant: "primary",
    icon: "import",
    onclick: async () => {
      load.disabled = true;
      clear(status);
      try {
        const { job_id: jobId } = await api.libraryImport(size === "all" ? null : Number(size));
        jobs.watch(jobId);
        append(status, notice("Loading started. Progress shows at the top of the page; you can keep using the app."));
      } catch (error) {
        load.disabled = false;
        append(status, notice(error.message, "error"));
      }
    },
  });
  return h(
    "div",
    { class: "library-loader" },
    h("div", { class: "field" }, h("span", {}, "How many puzzles"), segmented(sizes, size, (value) => {
      size = value;
      clear(hint).append(sizeHint(value));
    }, "How many puzzles")),
    hint,
    load,
    status,
  );
}

async function renderLibraryHub(container, context) {
  const user = context.user;
  const [library, rating] = await Promise.all([api.librarySummary(), api.puzzleRating(user.id)]);
  if (!library.total) {
    append(
      container,
      pageHeader("Puzzles", "Rated puzzles from real Lichess games, picked for your level."),
      sourceSwitch("lichess"),
      emptyState({
        iconName: "puzzle",
        title: "Load the Lichess puzzle database",
        text: "Millions of rated puzzles from real games, tagged by theme. Choose how many to load; only that part of the file is downloaded.",
        action: libraryLoader({ loaded: 0 }),
      }),
      h(
        "p",
        { class: "muted small footnote" },
        "Puzzles come from ",
        h("a", { href: "https://database.lichess.org/#puzzles", target: "_blank", rel: "noopener noreferrer" }, "database.lichess.org"),
        " (CC0). From a terminal: ",
        h("code", {}, "uv run chess-trainer-puzzle-library --limit 100000"),
      ),
    );
    return;
  }

  const level = Math.round(rating.rating);
  const prefs = loadPrefs();
  let difficulty = DIFFICULTIES.some(([value]) => value === prefs.difficulty) ? prefs.difficulty : "normal";
  let theme = library.themes.some((t) => t.theme === prefs.theme) ? prefs.theme : "";
  const history = loadHistory(user.id);
  const entries = Object.entries(history).filter(([key]) => key.startsWith(LIBRARY_PREFIX)).map(([, entry]) => entry);
  const solved = entries.filter((entry) => entry.solved);
  const firstTry = solved.filter((entry) => entry.firstTry).length;

  const status = h("div");
  const windowText = h("p", { class: "muted small" });
  const describeWindow = () => {
    const { rating_min: min, rating_max: max } = ratingWindow(difficulty, level);
    clear(windowText).append(min === null ? "Puzzles of every rating." : `Puzzles rated ${min}–${max}.`);
  };
  const start = button("Start solving", {
    variant: "primary",
    icon: "puzzle",
    onclick: async () => {
      start.disabled = true;
      clear(status);
      try {
        await openRandomLibraryPuzzle(filters());
      } catch (error) {
        append(status, notice(error.message, "error"));
      } finally {
        start.disabled = false;
      }
    },
  });
  const filters = () => ({ ...ratingWindow(difficulty, level), theme: theme || null });
  const grid = h("div", { class: "puzzle-grid" });
  let sampleToken = 0;
  const loadSample = async () => {
    const token = ++sampleToken;
    clear(grid).append(loading("Picking puzzles…"));
    let sample;
    try {
      sample = await api.librarySample(filters());
    } catch (error) {
      if (token === sampleToken) clear(grid).append(notice(error.message, "error"));
      return;
    }
    if (token !== sampleToken) return; // the filters changed meanwhile
    // Only puzzles still to solve; solved ones are not offered again here.
    sample = sample.filter((puzzle) => !isSolved(history, LIBRARY_PREFIX + puzzle.id));
    clear(grid);
    if (!sample.length) {
      append(grid, h("p", { class: "muted grid-empty" }, "No puzzles match these filters. Try another difficulty or theme, or load more puzzles."));
      return;
    }
    const query = filterQuery(filters());
    append(grid, sample.map((puzzle) => libraryCard(puzzle, history[LIBRARY_PREFIX + puzzle.id], query)));
  };
  const remember = () => {
    savePrefs({ difficulty, theme });
    loadSample();
  };
  const themeOptions = [["", "Any theme"], ...library.themes
    .map((t) => [t.theme, `${themeLabel(t.theme)} (${t.count.toLocaleString()})`])
    .sort((a, b) => a[1].localeCompare(b[1]))];
  const moreSlot = h("div");

  append(
    container,
    pageHeader("Puzzles", "Rated puzzles from real Lichess games, picked for your level.", start),
    sourceSwitch("lichess"),
    h(
      "div",
      { class: "stat-row" },
      statTile("Library", library.total.toLocaleString(), "Puzzles loaded from Lichess"),
      statTile("Your puzzle rating", `≈ ${level}`, rating.seeded ? "Estimated from your game ratings" : `After ${plural(rating.rated_attempts, "rated puzzle")}`),
      statTile("Solved", solved.length.toLocaleString(), solved.length ? `${Math.round((100 * firstTry) / solved.length)}% on the first try` : "None yet"),
    ),
    h(
      "div",
      { class: "toolbar" },
      segmented(DIFFICULTIES, difficulty, (value) => { difficulty = value; remember(); describeWindow(); }, "Difficulty"),
      select(themeOptions, theme, (value) => { theme = value; remember(); }, "Theme"),
      button("Shuffle", { icon: "retry", variant: "ghost", onclick: loadSample }),
    ),
    windowText,
    status,
    grid,
    h(
      "p",
      { class: "muted small footnote" },
      "Puzzles from ",
      h("a", { href: "https://database.lichess.org/#puzzles", target: "_blank", rel: "noopener noreferrer" }, "database.lichess.org"),
      " (CC0). Finished puzzles move your puzzle rating; the Solved marks are kept in this browser. ",
      h("button", { class: "link", type: "button", onclick: () => clear(moreSlot).append(libraryLoader({ loaded: library.total })) }, "Load more puzzles"),
    ),
    moreSlot,
  );
  describeWindow();
  loadSample();
}
