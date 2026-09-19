// Reusable interface pieces. Views compose these instead of restyling markup.

import { append, h, titleCase } from "./dom.js";
import { icon } from "./icons.js";

// One vocabulary for move quality, used by the board badge, move list, chips,
// charts and legends, so a blunder looks the same everywhere.
export const MOVE_KINDS = {
  brilliant: { label: "Brilliant move", symbol: "!!" },
  great: { label: "Great move", symbol: "!" },
  best: { label: "Best move", symbol: "★" },
  good: { label: "Good move", symbol: "✓" },
  book: { label: "Book move", symbol: "≡" },
  inaccuracy: { label: "Inaccuracy", symbol: "?!" },
  mistake: { label: "Mistake", symbol: "?" },
  blunder: { label: "Blunder", symbol: "??" },
};

/** Great and brilliant moves: shown with their mark wherever errors are. */
export const HIGHLIGHTS = ["brilliant", "great"];

export function moveKind(move) {
  if (move.highlight) return move.highlight;
  if (move.classification !== "good") return move.classification;
  if (move.in_book) return "book";
  return move.is_best ? "best" : "good";
}

export function kindBadge(kind, { withLabel = false } = {}) {
  const meta = MOVE_KINDS[kind];
  return h(
    "span",
    { class: `kind cls-${kind}`, title: meta.label },
    h("span", { class: "kind-symbol", "aria-hidden": "true" }, meta.symbol),
    withLabel ? meta.label : h("span", { class: "sr-only" }, meta.label),
  );
}

/** The API's plain-language reasons for a move, as a list. `kind` is a
 * MOVE_KINDS key and colours the bullets. */
export function reasonList(reasons, kind) {
  if (!reasons?.length) return null;
  return h(
    "ul",
    { class: "reasons" },
    reasons.map((reason) => h("li", { "data-code": reason.code }, h("span", { class: `reason-dot cls-${kind}`, "aria-hidden": "true" }), h("span", {}, reason.text))),
  );
}

export function pageHeader(title, subtitle, ...actions) {
  return h(
    "header",
    { class: "page-header" },
    h("div", {}, h("h1", {}, title), subtitle ? h("p", { class: "muted" }, subtitle) : null),
    actions.length ? h("div", { class: "page-actions" }, actions) : null,
  );
}

/** button("Label", { variant: "primary" | "ghost", icon, href, onclick, ...attrs }) */
export function button(label, { variant = "", icon: iconName, href, ...attrs } = {}) {
  const classes = `btn ${variant ? `btn-${variant}` : ""}${label ? "" : " btn-icon"}`;
  const content = [iconName ? icon(iconName, 18) : null, label ? h("span", {}, label) : null];
  return href
    ? h("a", { class: classes, href, ...attrs }, content)
    : h("button", { class: classes, type: "button", ...attrs }, content);
}

export function panel(title, ...children) {
  return h("section", { class: "panel" }, title ? h("h2", { class: "panel-title" }, title) : null, children);
}

export function statTile(label, value, hint) {
  return h(
    "div",
    { class: "stat" },
    h("div", { class: "stat-label" }, label),
    h("div", { class: "stat-value" }, value),
    hint ? h("div", { class: "stat-hint" }, hint) : null,
  );
}

export function emptyState({ iconName = "games", title, text, action }) {
  return h(
    "div",
    { class: "empty" },
    h("div", { class: "empty-icon" }, icon(iconName, 28)),
    h("h2", {}, title),
    text ? h("p", { class: "muted" }, text) : null,
    action || null,
  );
}

// Lichess theme keys are camelCase ("mateIn2", "hangingPiece"); a few need
// hand-written labels, the rest are split into words.
const THEME_LABELS = {
  superGM: "Super GM game",
  masterVsMaster: "Master vs master",
  oneMove: "One-move",
  xRayAttack: "X-ray attack",
  enPassant: "En passant",
  mix: "Healthy mix",
};

export function themeLabel(theme) {
  if (THEME_LABELS[theme]) return THEME_LABELS[theme];
  const words = String(theme)
    .replace(/([a-z])([A-Z0-9])/g, "$1 $2")
    .replaceAll("_", " ")
    .toLowerCase();
  return words.charAt(0).toUpperCase() + words.slice(1);
}

export function chip(text, kind = "") {
  return h("span", { class: `chip ${kind ? `cls-${kind}` : ""}` }, text);
}

export function resultPill(outcome) {
  const text = { win: "Won", loss: "Lost", draw: "Draw" }[outcome] || "—";
  return h("span", { class: `result result-${outcome || "none"}` }, text);
}

export function colorDot(color) {
  return h("span", { class: `color-dot ${color}`, title: `Played ${color}` });
}

export function spinner() {
  return h("span", { class: "spinner", role: "status", "aria-label": "Loading" });
}

export function loading(text = "Loading…") {
  return h("div", { class: "loading" }, spinner(), h("span", {}, text));
}

export function notice(text, kind = "") {
  return h("p", { class: `notice ${kind ? `notice-${kind}` : ""}`, role: kind === "error" ? "alert" : null }, text);
}

/** Exclusive choice shown as joined buttons. options: [[value, label], ...] */
export function segmented(options, value, onChange, label) {
  const group = h("div", { class: "segmented", role: "group", "aria-label": label });
  const buttons = options.map(([optionValue, optionLabel]) =>
    h(
      "button",
      {
        type: "button",
        "aria-pressed": String(optionValue === value),
        onclick: () => {
          buttons.forEach((b) => b.setAttribute("aria-pressed", String(b === buttons[index(optionValue)])));
          onChange(optionValue);
        },
      },
      optionLabel,
    ),
  );
  const index = (wanted) => options.findIndex(([v]) => v === wanted);
  return append(group, buttons);
}

export function select(options, value, onChange, label) {
  const element = h(
    "select",
    { class: "select", "aria-label": label, onchange: () => onChange(element.value) },
    options.map(([optionValue, optionLabel]) => h("option", { value: optionValue }, optionLabel)),
  );
  element.value = value;
  return element;
}

/** Ask before a destructive action. Resolves true if confirmed. */
export function confirmDialog({ title, text, confirmLabel = "Confirm" }) {
  return new Promise((resolve) => {
    const dialog = h(
      "dialog",
      { class: "dialog" },
      h("h2", {}, title),
      h("p", { class: "muted" }, text),
      h(
        "div",
        { class: "dialog-actions" },
        button("Cancel", { onclick: () => dialog.close("cancel") }),
        button(confirmLabel, { variant: "danger", onclick: () => dialog.close("confirm") }),
      ),
    );
    dialog.addEventListener("close", () => {
      resolve(dialog.returnValue === "confirm");
      dialog.remove();
    });
    document.body.append(dialog);
    dialog.showModal();
  });
}

export const PLATFORM_LABEL = { lichess: "Lichess", chesscom: "Chess.com" };

export function platformBadge(platform) {
  return h("span", { class: `platform platform-${platform}` }, PLATFORM_LABEL[platform] || titleCase(platform));
}

export function opponentOf(row) {
  const game = row.game;
  return row.user_color === "white"
    ? { name: game.black_username, rating: game.black_rating }
    : { name: game.white_username, rating: game.white_rating };
}
