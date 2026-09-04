// Training hub: your puzzles, what's solved, and a way to start.

import { api } from "../api.js";
import { miniBoard } from "../board.js";
import { append, clear, h, plural, titleCase } from "../dom.js";
import { clearHistory, isSolved, loadHistory } from "../history.js";
import { button, chip, confirmDialog, emptyState, pageHeader, segmented, statTile } from "../ui.js";

const PHASES = [["", "All"], ["opening", "Opening"], ["middlegame", "Middlegame"], ["endgame", "Endgame"]];
const STATUSES = [["", "All"], ["unsolved", "Unsolved"], ["solved", "Solved"]];

export async function renderPuzzles(container, context) {
  const user = context.user;
  const puzzles = await api.puzzles(user.id);
  if (!puzzles.length) {
    append(
      container,
      pageHeader("Puzzles", "Positions from your own games where you went wrong."),
      emptyState({
        iconName: "puzzle",
        title: "No puzzles yet",
        text: "A puzzle is created when you make a mistake in a position that had one clearly best move. Import and analyze more games to get some.",
        action: button("Import games", { variant: "primary", icon: "import", href: "#/import" }),
      }),
    );
    return;
  }

  let history = loadHistory(user.id);
  let phase = PHASES.some(([value]) => value === context.query.phase) ? context.query.phase : "";
  let status = "";
  const summary = h("div", { class: "stat-row" });
  const grid = h("div", { class: "puzzle-grid" });
  const startSlot = h("span");

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
    clear(grid);
    if (!visible.length) {
      append(grid, h("p", { class: "muted grid-empty" }, "No puzzles match these filters."));
      return;
    }
    append(grid, visible.map((puzzle) => puzzleCard(puzzle, history[puzzle.id])));
  };

  append(
    container,
    pageHeader("Puzzles", "Positions from your own games where you went wrong. Find the move you missed.", startSlot),
    summary,
    h(
      "div",
      { class: "toolbar" },
      segmented(PHASES, phase, (value) => { phase = value; render(); }, "Game phase"),
      segmented(STATUSES, status, (value) => { status = value; render(); }, "Status"),
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
      h("div", { class: "chips" }, chip(`Your ${puzzle.severity}`, puzzle.severity), puzzle.themes.map((theme) => chip(titleCase(theme)))),
    ),
  );
}
