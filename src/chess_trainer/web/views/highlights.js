// Great and brilliant moves: the best moves you found in your imported games.
// Each card shows the position after the move; it opens the game at that move.

import { api } from "../api.js";
import { Board } from "../board.js";
import { append, clear, formatDate, h, plural, titleCase } from "../dom.js";
import { jobs } from "../jobs.js";
import { MOVE_KINDS, button, emptyState, kindBadge, notice, opponentOf, pageHeader, segmented } from "../ui.js";
import { Chess } from "../vendor/chess.js";

const PAGE = 48;

export async function renderHighlights(container, context) {
  const user = context.user;
  let kind = "";
  let shown = [];
  let report = null;

  const filterSlot = h("div");
  const checkSlot = h("div");
  const grid = h("div", { class: "puzzle-grid" });
  const more = h("div", { class: "more" });

  async function load({ append: adding = false } = {}) {
    const page = await api.highlights(user.id, { kind, limit: PAGE, offset: adding ? shown.length : 0 });
    report = page;
    shown = adding ? [...shown, ...page.moves] : page.moves;
    render();
  }

  function render() {
    const total = report.great + report.brilliant;
    clear(filterSlot);
    filterSlot.hidden = !total;
    if (total) {
      append(
        filterSlot,
        segmented(
          [
            ["", `All (${total})`],
            ["brilliant", `Brilliant (${report.brilliant})`],
            ["great", `Great (${report.great})`],
          ],
          kind,
          (value) => {
            kind = value;
            load();
          },
          "Show",
        ),
      );
    }
    clear(checkSlot);
    checkSlot.hidden = !report.unchecked_games;
    if (report.unchecked_games) append(checkSlot, checkNotice(report.unchecked_games, user));

    clear(grid);
    clear(more);
    if (!shown.length) {
      append(grid, emptyMessage(total, report.unchecked_games));
      return;
    }
    append(grid, shown.map((move) => highlightCard(move)));
    const available = kind === "brilliant" ? report.brilliant : kind === "great" ? report.great : total;
    if (shown.length < available) {
      append(more, button(`Show more (${available - shown.length} left)`, { onclick: () => load({ append: true }) }));
    }
  }

  append(
    container,
    h("a", { class: "back", href: "#/games" }, "← All games"),
    pageHeader("Great and brilliant moves", "The moves from your games that the engine rates highest."),
    legend(),
    checkSlot,
    filterSlot,
    grid,
    more,
  );
  await load();
}

function legend() {
  const item = (kind, text) => h("li", {}, kindBadge(kind, { withLabel: true }), h("span", { class: "muted" }, text));
  return h(
    "ul",
    { class: "highlight-legend" },
    item("brilliant", "A sacrifice that works: you gave up material and it was still the best move."),
    item("great", "The only good move: every other move threw away a big part of your winning chances."),
  );
}

/** Games analyzed before this check existed: offer to check them now. */
function checkNotice(count, user) {
  const start = button(`Check ${plural(count, "game")}`, {
    variant: "primary",
    icon: "star",
    onclick: async () => {
      start.disabled = true;
      try {
        const queued = await Promise.all(user.accounts.map((account) => api.analyzeAccount(account.id)));
        jobs.watch(queued[queued.length - 1].job_id);
        message.textContent = "Checking. Progress shows in the banner, and this page updates when it's done.";
      } catch {
        start.disabled = false;
        message.textContent = "Couldn't start the check. Is the server running?";
      }
    },
  });
  const message = h(
    "span",
    {},
    `${plural(count, "analyzed game")} ${count === 1 ? "hasn't" : "haven't"} been checked for great and brilliant moves yet. `,
    "The worker runs a second engine line where a move could be the only good one.",
  );
  return h("div", { class: "notice highlight-check" }, message, jobs.active ? null : start);
}

function emptyMessage(total, unchecked) {
  if (total) return notice("None of this kind yet.");
  return emptyState({
    iconName: "star",
    title: unchecked ? "Not checked yet" : "No great or brilliant moves yet",
    text: unchecked
      ? "Check your analyzed games above to find them."
      : "They're rare: a few in every few dozen games. New games are checked as they're analyzed.",
    action: unchecked ? null : button("Import games", { icon: "import", href: "#/import" }),
  });
}

/** The position after the move, with the move marked, linking to the game at that move. */
function highlightCard(move) {
  const board = new Board({ orientation: move.color, coords: false });
  board.element.classList.add("mini");
  const chess = new Chess(move.fen_before);
  try {
    chess.move({ from: move.uci.slice(0, 2), to: move.uci.slice(2, 4), promotion: move.uci[4] });
  } catch {
    /* stored moves are legal; fall back to the position before */
  }
  board.setPosition(chess.fen());
  board.setMarks({ lastMove: [move.uci.slice(0, 2), move.uci.slice(2, 4)] });
  board.setBadge({ square: move.uci.slice(2, 4), kind: move.kind, symbol: MOVE_KINDS[move.kind].symbol });

  const opponent = opponentOf({ game: move.game, user_color: move.color });
  const number = `${move.move_number}${move.color === "white" ? "." : "..."}`;
  return h(
    "a",
    { class: "puzzle-card highlight-card", href: `#/games/${move.game.id}/${move.ply}` },
    h("div", { class: "puzzle-thumb" }, board.element),
    h(
      "div",
      { class: "puzzle-card-body" },
      h("div", { class: "puzzle-card-title" }, kindBadge(move.kind), h("span", { class: `cls-${move.kind}` }, `${number} ${move.san}`)),
      h("div", { class: "muted small" }, `vs ${opponent.name} · ${titleCase(move.game.time_class)} · ${formatDate(move.game.played_at)}`),
      h("div", { class: "small" }, move.explanation),
    ),
  );
}
