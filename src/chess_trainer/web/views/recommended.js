// "For you": Lichess puzzles picked from your puzzle rating, the mistakes in
// your own games and the openings you play. The hub shows why each kind of
// puzzle is there; the puzzle page works through the same set in order.

import { api } from "../api.js";
import { append, clear, h, plural } from "../dom.js";
import { button, emptyState, loading, notice, pageHeader, panel, statTile } from "../ui.js";
import { libraryCard } from "./library-card.js";

export const RECOMMENDED_HUB = "#/puzzles?source=foryou";
const GROUPS = [
  ["tactic", "From your mistakes"],
  ["opening", "Openings you play"],
  ["phase", "Where your mistakes happen"],
  ["level", "Your level"],
];
// Below this, filtering by rating, theme and opening often leaves too few puzzles.
const SMALL_LIBRARY = 100000;
const queueKey = (userId) => `chessTrainer.forYou.${userId}`;

/** The current set of recommendations: [{ id, focus }], kept for this tab. */
export function loadQueue(userId) {
  try {
    return JSON.parse(sessionStorage.getItem(queueKey(userId)) || "[]");
  } catch {
    return [];
  }
}

function saveQueue(userId, recommendations) {
  const queue = recommendations.map(({ puzzle, focus }) => ({ id: puzzle.id, focus }));
  try {
    sessionStorage.setItem(queueKey(userId), JSON.stringify(queue));
  } catch {
    /* storage unavailable: "next" just fetches a fresh set each time */
  }
  return queue;
}

export const recommendedHref = (puzzleId) => `#/puzzles/lichess/${encodeURIComponent(puzzleId)}?for=you`;

/** Why this puzzle was recommended, if it came from the current set. */
export function focusOf(userId, puzzleId) {
  return loadQueue(userId).find((item) => item.id === puzzleId)?.focus || null;
}

/**
 * What a card or the trainer may say before the puzzle is solved. A tactic's
 * name would give the answer away, so those only say where they come from.
 */
export function focusLabel(focus) {
  if (focus.group === "tactic") return "From your mistakes";
  if (focus.group === "opening") return `Your opening: ${focus.title}`;
  if (focus.group === "phase") return `${focus.title} practice`;
  return "At your level";
}

/** Open the puzzle after `currentId` in the set, fetching a new set at the end. */
export async function openNextRecommended(userId, currentId) {
  const queue = loadQueue(userId);
  const next = queue[queue.findIndex((item) => item.id === currentId) + 1];
  // findIndex is -1 for a puzzle outside the set, which restarts it at the top.
  if (next && next.id !== currentId) {
    location.hash = recommendedHref(next.id);
    return;
  }
  const fresh = await api.recommended(userId, { exclude: currentId });
  if (!fresh.length) throw new Error("No more puzzles to recommend. Load more of the Lichess database from the Puzzles page.");
  saveQueue(userId, fresh);
  location.hash = recommendedHref(fresh[0].puzzle.id);
}

function ratingTile(rating) {
  const value = `≈ ${Math.round(rating.rating)}`;
  if (rating.seeded) return statTile("Puzzle rating", value, "Estimated from your game ratings. Your first puzzles will move it quickly.");
  return statTile("Puzzle rating", value, `± ${Math.round(rating.deviation)} after ${plural(rating.rated_attempts, "rated puzzle")}`);
}

function focusPanel(profile) {
  const groups = GROUPS.map(([group, label]) => [label, profile.foci.filter((focus) => focus.group === group)]).filter(([, foci]) => foci.length);
  return panel(
    "What you're training and why",
    h(
      "div",
      { class: "focus-groups" },
      groups.map(([label, foci]) =>
        h(
          "div",
          { class: "focus-group" },
          h("h3", { class: "focus-group-title" }, label),
          h("ul", { class: "focus-list" }, foci.map((focus) => h("li", {}, h("strong", {}, focus.title), h("span", { class: "muted small" }, focus.reason)))),
        ),
      ),
    ),
  );
}

export async function renderRecommendedHub(container, context, sourceSwitch) {
  const user = context.user;
  const subtitle = "Lichess puzzles picked from your rating, your mistakes and the openings you play.";
  const profile = await api.training(user.id);
  if (!profile.library_size) {
    append(
      container,
      pageHeader("Puzzles", subtitle),
      sourceSwitch,
      emptyState({
        iconName: "puzzle",
        title: "Load the Lichess puzzle database first",
        text: "Recommendations are picked from the Lichess puzzle database, which isn't loaded yet.",
        action: button("Load puzzles", { variant: "primary", icon: "import", href: "#/puzzles?source=lichess" }),
      }),
    );
    return;
  }

  const grid = h("div", { class: "puzzle-grid" });
  const status = h("div");
  let first = null;
  let token = 0;
  const loadSet = async () => {
    const mine = ++token;
    first = null;
    clear(status);
    clear(grid).append(loading("Picking puzzles for you…"));
    let recommendations;
    try {
      recommendations = await api.recommended(user.id);
    } catch (error) {
      if (mine === token) clear(grid).append(notice(error.message, "error"));
      return;
    }
    if (mine !== token) return;
    clear(grid);
    if (!recommendations.length) {
      append(grid, h("p", { class: "muted grid-empty" }, "You've been through every puzzle near your rating. Load more of the Lichess database to get new ones."));
      return;
    }
    saveQueue(user.id, recommendations);
    first = recommendations[0].puzzle.id;
    append(grid, recommendations.map(({ puzzle, focus }) => libraryCard(puzzle, null, "?for=you", focusLabel(focus))));
  };
  const start = button("Start training", {
    variant: "primary",
    icon: "puzzle",
    onclick: () => {
      if (first) location.hash = recommendedHref(first);
    },
  });

  const { progress } = profile;
  append(
    container,
    pageHeader("Puzzles", subtitle, start),
    sourceSwitch,
    h(
      "div",
      { class: "stat-row" },
      ratingTile(profile.rating),
      statTile(
        "Solved",
        progress.puzzles ? `${progress.solved} of ${progress.puzzles}` : "—",
        progress.puzzles ? `${Math.round((100 * progress.first_try) / progress.puzzles)}% cleanly on the first attempt` : "No Lichess puzzles attempted yet",
      ),
      statTile(
        "Based on",
        profile.mistakes ? plural(profile.mistakes, "mistake") : "Your level",
        profile.mistakes ? `Your most recent mistakes and blunders, from ${plural(profile.games, "game")}` : "Analyze some games to add your mistakes and openings",
      ),
    ),
    profile.mistakes ? null : notice("No analyzed games yet, so these are puzzles at your level. Import and analyze games to have them follow your mistakes."),
    focusPanel(profile),
    h("div", { class: "toolbar" }, h("h2", { class: "section-title" }, "Your next puzzles"), button("New set", { icon: "retry", variant: "ghost", onclick: loadSet })),
    status,
    grid,
    h(
      "p",
      { class: "muted small footnote" },
      "Each puzzle you finish is saved to your profile and moves your puzzle rating; a puzzle only counts the first time. ",
      profile.library_size < SMALL_LIBRARY
        ? [
            `Only ${profile.library_size.toLocaleString()} puzzles are loaded, so matches by tactic and opening are limited. `,
            h("a", { href: "#/puzzles?source=lichess" }, "Load more"),
            ".",
          ]
        : null,
    ),
  );
  loadSet();
}
