// Mistakes you make more than once: positions where you went wrong in several
// games, grouped across move orders and opening names. The helpers here are
// shared with the Stats page and the opening explorer.

import { api } from "../api.js";
import { Board, checkedKingSquare } from "../board.js";
import { append, clear, formatDate, h, plural, titleCase } from "../dom.js";
import { createPlayOn } from "../playon.js";
import { button, chip, colorDot, emptyState, kindBadge, pageHeader, panel, reasonList, select } from "../ui.js";
import { Chess } from "../vendor/chess.js";
import { arrowOf } from "./game.js";

const TIME_CLASSES = ["bullet", "blitz", "rapid", "classical", "correspondence"];
// Engine lines get speculative past this many plies.
const MAX_LINE_PLIES = 10;

/** "#/stats/repeated?..." keeping the Stats page filters, optionally opening one group. */
export function repeatedHref(filters = {}, key = null) {
  const params = new URLSearchParams();
  for (const name of ["time_class", "account_id"]) if (filters[name]) params.set(name, filters[name]);
  if (key) params.set("key", key);
  const text = params.toString();
  return `#/stats/repeated${text ? `?${text}` : ""}`;
}

const dots = (color) => (color === "white" ? "." : "...");
const moveText = (group, san) => `${group.move_number}${dots(group.color)} ${san}`;

/** ["e4", "e5", "Nf3"] -> "1. e4 e5 2. Nf3" */
export function numberedLine(sans) {
  return sans.map((san, i) => (i % 2 === 0 ? `${i / 2 + 1}. ${san}` : san)).join(" ");
}

/** Arrows for the board: what you played (red, most common first) and the better move (green). */
export function repeatedArrows(group) {
  return [
    ...group.played.map((move) => ({ ...arrowOf(move.uci), kind: "played" })),
    ...(group.best_move_uci ? [{ ...arrowOf(group.best_move_uci), kind: "best" }] : []),
  ];
}

/** The engine's best line from the mistake position: [{ uci, san, fen, number }]. */
export function continuationSteps(group) {
  const chess = new Chess(group.fen);
  const steps = [];
  for (const uci of (group.best_line || []).slice(0, MAX_LINE_PLIES)) {
    const number = chess.moveNumber();
    const white = chess.turn() === "w";
    try {
      const move = chess.move({ from: uci.slice(0, 2), to: uci.slice(2, 4), promotion: uci[4] });
      steps.push({ uci, san: move.san, fen: chess.fen(), number, white });
    } catch {
      break;
    }
  }
  return steps;
}

/**
 * The best continuation, playable on `board`: clicking a move (or stepping)
 * shows the position after it; step -1 is the mistake position with its arrows.
 * From any of those positions "Play on from here" lets you carry on against
 * the engine with your moves scored (playon.js).
 * Returns { element, go(index), step(direction), redraw(), stop() }.
 */
export function continuation(group, board) {
  const found = continuationSteps(group);
  const steps = found.length > 1 ? found : []; // a single move is already shown as the better move
  let at = -1;
  const play = createPlayOn({ board, exitLabel: "Back to the line", onExit: () => go(at) });
  const cells = steps.map((step, i) =>
    h(
      "button",
      { class: "move", type: "button", onclick: () => go(i) },
      step.white || i === 0 ? h("span", { class: "move-number" }, `${step.number}${step.white ? "." : "..."}`) : null,
      step.san,
    ),
  );
  const back = button("", { icon: "prev", "aria-label": "Previous move of the line", title: "Previous move (←)", onclick: () => go(at - 1) });
  const forward = button("", { icon: "next", "aria-label": "Next move of the line", title: "Next move (→)", onclick: () => go(at + 1) });
  const reset = button("Back to the mistake", { icon: "retry", variant: "ghost", onclick: () => go(-1) });

  const playButton = button("Play on from here", {
    icon: "arrow",
    title: "Carry on against the engine; your moves are scored like in game analysis",
    onclick: () => {
      browse.hidden = true;
      play.start(at < 0 ? group.fen : steps[at].fen, group.color);
    },
  });
  const browse = h(
    "div",
    {},
    steps.length ? [h("p", { class: "result-why" }, "Best continuation"), h("div", { class: "line-moves" }, cells)] : null,
    h("div", { class: "continuation-controls" }, steps.length ? [back, forward] : null, playButton, reset),
  );

  function go(index) {
    play.stop(true);
    browse.hidden = false;
    at = Math.min(Math.max(index, -1), steps.length - 1);
    board.setBadge(null);
    if (at < 0) {
      board.setPosition(group.fen);
      board.setMarks({});
      board.setArrows(repeatedArrows(group));
    } else {
      const step = steps[at];
      board.setPosition(step.fen);
      board.setMarks({ lastMove: [step.uci.slice(0, 2), step.uci.slice(2, 4)], check: checkedKingSquare(new Chess(step.fen)) });
      board.setArrows([]);
    }
    cells.forEach((cell, i) => cell.classList.toggle("current", i === at));
    back.disabled = at < 0;
    forward.disabled = at === steps.length - 1;
    reset.hidden = at < 0;
  }

  const element = h("div", { class: "continuation" }, browse, play.element);
  go(-1);
  return {
    element,
    go,
    // While playing on, the arrow keys and a board flip leave the game alone.
    step: (direction) => play.active() || go(at + direction),
    redraw: () => play.active() || go(at),
    stop: () => play.stop(true),
  };
}

/** One line in a list of repeated mistakes. */
export function repeatedRow(group, { href = null, onclick = null, selected = false } = {}) {
  const top = group.played[0];
  return h(
    href ? "a" : "button",
    { class: `game-row${selected ? " selected" : ""}`, ...(href ? { href } : { type: "button", onclick }) },
    kindBadge(group.worst),
    h(
      "div",
      { class: "game-row-main" },
      h(
        "div",
        {},
        h("strong", { class: `cls-${group.worst}` }, moveText(group, top.san)),
        group.played.length > 1 ? h("span", { class: "muted small" }, ` and ${plural(group.played.length - 1, "other move")}`) : null,
        group.best_move_san ? h("span", { class: "muted" }, " · better ", h("strong", { class: "cls-best" }, group.best_move_san)) : null,
      ),
      h("div", { class: "muted small" }, group.path.length ? numberedLine(group.path) : `Move ${group.move_number}`, " · ", group.families.join(", ")),
    ),
    h("div", { class: "game-row-stats" }, h("strong", {}, plural(group.games, "game")), h("span", { class: "muted small" }, `−${Math.round(group.average_win_pct_loss)}% avg`)),
  );
}

/**
 * What went wrong here and in which games. `gameLink(occurrence)` returns the
 * attributes (href or onclick) of the link to each game; `line` is the
 * playable best continuation, if any.
 */
export function repeatedCoach(group, { gameLink, line = null }) {
  const latest = group.occurrences[0];
  const kind = group.worst;
  return [
    h(
      "div",
      { class: "coach-head" },
      kindBadge(kind),
      h("strong", {}, `You went wrong here in ${plural(group.games, "game")}`),
    ),
    h("p", { class: "muted small" }, group.path.length ? `After ${numberedLine(group.path)}` : `Move ${group.move_number}`, `, ${titleCase(group.color)} to move.`),
    h(
      "p",
      {},
      "You played ",
      group.played.map((move, i) => [
        i ? (i === group.played.length - 1 ? " and " : ", ") : "",
        h("strong", { class: `cls-${kind}` }, moveText(group, move.san)),
        group.played.length > 1 || move.count > 1 ? ` (${plural(move.count, "game")})` : "",
      ]),
      `, giving away about ${Math.round(group.average_win_pct_loss)}% of your winning chances on average.`,
    ),
    group.best_move_san
      ? h("div", { class: "coach-best" }, h("div", {}, "You should play ", h("strong", { class: "cls-best" }, moveText(group, group.best_move_san)), " here."))
      : null,
    line ? line.element : null,
    group.explanation.length ? h("p", { class: "result-why" }, `Why ${latest.san} goes wrong`) : null,
    reasonList(group.explanation, kind),
    h(
      "ul",
      { class: "occurrences" },
      group.occurrences.map((occurrence) =>
        h(
          "li",
          {},
          h("a", gameLink(occurrence), `${formatDate(occurrence.played_at) || "Undated game"}`),
          h("span", { class: "muted small" }, occurrence.opening_family || "Unknown opening"),
          chip(moveText(group, occurrence.san), occurrence.classification),
        ),
      ),
    ),
  ];
}

export async function renderRepeated(container, context) {
  const user = context.user;
  const filters = { time_class: context.query.time_class || "", account_id: context.query.account_id || "" };
  const body = h("div");
  let keys = null; // key -> action, once groups are shown
  let stop = null; // ends "play on", if running

  const load = async () => {
    const groups = await api.repeatedMistakes(user.id, { ...filters, limit: 50 });
    stop?.();
    const shown = repeatedBody(groups, filters, context.query.key);
    keys = shown.keys;
    stop = shown.stop || null;
    clear(body);
    append(body, shown.view);
  };
  const change = (key) => (value) => {
    filters[key] = value;
    history.replaceState(null, "", repeatedHref(filters));
    context.query.key = null;
    load();
  };

  append(
    container,
    h("a", { class: "back", href: "#/stats" }, "← Stats"),
    pageHeader(
      "Mistakes you repeat",
      "Positions where you went wrong in more than one game.",
      select([["", "All time controls"], ...TIME_CLASSES.map((t) => [t, titleCase(t)])], filters.time_class, change("time_class"), "Time control"),
      user.accounts.length > 1
        ? select([["", "All accounts"], ...user.accounts.map((a) => [String(a.id), `${a.username} (${a.platform})`])], filters.account_id, change("account_id"), "Account")
        : null,
    ),
    body,
  );
  const onKey = (event) => {
    if (!keys || event.target.matches("input, select, textarea") || event.metaKey || event.ctrlKey) return;
    const action = keys[event.key];
    if (action) {
      event.preventDefault();
      action();
    }
  };
  document.addEventListener("keydown", onKey);
  await load();
  return () => {
    stop?.();
    document.removeEventListener("keydown", onKey);
  };
}

function repeatedBody(groups, filters, wantedKey) {
  if (!groups.length) {
    return {
      keys: null,
      view: emptyState({
        iconName: "stats",
        title: "No repeated mistakes",
        text: "None of your errors happened in the same position in two games. More analyzed games make habits easier to spot.",
        action: button("Back to Stats", { href: "#/stats" }),
      }),
    };
  }
  const board = new Board({ orientation: groups[0].color });
  const caption = h("div", { class: "player opening-caption" });
  const coach = h("div", { class: "coach", "aria-live": "polite" });
  const rows = [];
  let line = null; // the shown group's playable best continuation
  let current = Math.max(0, groups.findIndex((g) => g.key === wantedKey));

  const show = (index) => {
    current = (index + groups.length) % groups.length;
    const group = groups[current];
    board.setOrientation(group.color);
    line?.stop();
    line = continuation(group, board);
    clear(caption).append(colorDot(group.color), h("strong", {}, `${titleCase(group.color)} to move`), h("span", { class: "muted" }, `Mistake ${current + 1} of ${groups.length}`));
    clear(coach).append(...repeatedCoach(group, { gameLink: (o) => ({ href: `#/games/${o.game_id}/${o.ply}` }), line }).filter(Boolean));
    rows.forEach((row, i) => row.classList.toggle("selected", i === current));
    history.replaceState(null, "", repeatedHref(filters, group.key));
  };

  const list = h(
    "ul",
    { class: "game-list" },
    groups.map((group, index) => {
      const row = repeatedRow(group, { onclick: () => show(index) });
      rows.push(row);
      return h("li", {}, row);
    }),
  );

  const view = h(
    "div",
    { class: "analysis opening-explorer" },
    h(
      "div",
      { class: "analysis-board" },
      caption,
      board.element,
      h(
        "div",
        { class: "controls" },
        button("Previous", { icon: "prev", title: "Previous mistake (↑)", onclick: () => show(current - 1) }),
        button("Next mistake", { icon: "skip", variant: "primary", title: "Next mistake (↓)", onclick: () => show(current + 1) }),
      ),
      h("p", { class: "muted small" }, "Red arrows: what you played. Green: the better move. ← → play through the best continuation, ↑ ↓ change mistake. \"Play on from here\" lets you continue against the engine with your moves scored."),
    ),
    h("div", { class: "analysis-side" }, panel(null, coach), panel(`All repeated mistakes (${groups.length})`, list)),
  );
  show(current);
  return {
    view,
    stop: () => line?.stop(),
    keys: {
      ArrowUp: () => show(current - 1),
      ArrowDown: () => show(current + 1),
      ArrowLeft: () => line?.step(-1),
      ArrowRight: () => line?.step(1),
    },
  };
}
