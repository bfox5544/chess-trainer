// A card for one Lichess library puzzle, shared by the puzzle hubs.

import { miniBoard } from "../board.js";
import { h, plural, titleCase } from "../dom.js";

/** `query` rides along to the puzzle page; `note` is an extra line (why it was picked). */
export function libraryCard(puzzle, entry, query, note = null) {
  const userMoves = puzzle.solution.filter((step) => step.by === "user").length;
  return h(
    "a",
    { class: `puzzle-card${entry?.solved ? " solved" : ""}`, href: `#/puzzles/lichess/${encodeURIComponent(puzzle.id)}${query}` },
    // The position the solver faces, after the opponent's setup move.
    h("div", { class: "puzzle-thumb" }, miniBoard(puzzle.start_fen, puzzle.user_color), entry?.solved ? h("span", { class: "solved-mark" }, "Solved") : null),
    h(
      "div",
      { class: "puzzle-card-body" },
      h("div", { class: "puzzle-card-title" }, h("span", { class: `color-dot ${puzzle.user_color}` }), `${titleCase(puzzle.user_color)} to move`),
      h("div", { class: "muted small" }, `Rated ${puzzle.rating} · ${plural(userMoves, "move")} to find`),
      note ? h("div", { class: "puzzle-card-note small" }, note) : null,
    ),
  );
}
