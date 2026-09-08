// Mistakes you make more than once: positions where you went wrong in several
// games, grouped across move orders and opening names. The helpers here are
// shared with the Stats page and the opening explorer.

import { api } from "../api.js";
import { Board } from "../board.js";
import { append, clear, formatDate, h, plural, titleCase } from "../dom.js";
import { button, chip, colorDot, emptyState, kindBadge, pageHeader, panel, reasonList, select } from "../ui.js";
import { arrowOf } from "./game.js";

const TIME_CLASSES = ["bullet", "blitz", "rapid", "classical", "correspondence"];

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
 * attributes (href or onclick) of the link to each game.
 */
export function repeatedCoach(group, { gameLink }) {
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
  let step = null; // (direction) => void, once groups are shown

  const load = async () => {
    const groups = await api.repeatedMistakes(user.id, { ...filters, limit: 50 });
    const shown = repeatedBody(groups, filters, context.query.key);
    step = shown.step;
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
    if (!step || event.target.matches("input, select, textarea") || event.metaKey || event.ctrlKey) return;
    const direction = { ArrowLeft: -1, ArrowRight: 1 }[event.key];
    if (direction) {
      event.preventDefault();
      step(direction);
    }
  };
  document.addEventListener("keydown", onKey);
  await load();
  return () => document.removeEventListener("keydown", onKey);
}

function repeatedBody(groups, filters, wantedKey) {
  if (!groups.length) {
    return {
      step: null,
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
  let current = Math.max(0, groups.findIndex((g) => g.key === wantedKey));

  const show = (index) => {
    current = (index + groups.length) % groups.length;
    const group = groups[current];
    board.setOrientation(group.color);
    board.setPosition(group.fen);
    board.setArrows(repeatedArrows(group));
    clear(caption).append(colorDot(group.color), h("strong", {}, `${titleCase(group.color)} to move`), h("span", { class: "muted" }, `Mistake ${current + 1} of ${groups.length}`));
    clear(coach).append(...repeatedCoach(group, { gameLink: (o) => ({ href: `#/games/${o.game_id}/${o.ply}` }) }).filter(Boolean));
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
        button("Previous", { icon: "prev", title: "Previous (←)", onclick: () => show(current - 1) }),
        button("Next mistake", { icon: "skip", variant: "primary", title: "Next (→)", onclick: () => show(current + 1) }),
      ),
      h("p", { class: "muted small" }, "Red arrows: what you played. Green: the better move."),
    ),
    h("div", { class: "analysis-side" }, panel(null, coach), panel(`All repeated mistakes (${groups.length})`, list)),
  );
  show(current);
  return { view, step: (direction) => show(current + direction) };
}
