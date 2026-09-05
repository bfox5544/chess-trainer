// Solve a puzzle from the Lichess puzzle database. Filters (rating window,
// theme) ride along in the URL so "Next puzzle" keeps picking the same kind.

import { api } from "../api.js";
import { h, plural } from "../dom.js";
import { mountTrainer } from "../trainer.js";
import { button, chip, themeLabel } from "../ui.js";

export const LIBRARY_PREFIX = "lichess:"; // history keys, kept apart from your own puzzle ids

/** Filters from the URL query: { min, max, theme } -> API parameters. */
export function libraryFilters(query) {
  const number = (value) => (value && /^\d+$/.test(value) ? Number(value) : null);
  return { rating_min: number(query.min), rating_max: number(query.max), theme: query.theme || null };
}

export function filterQuery(filters) {
  const params = new URLSearchParams();
  if (filters.rating_min !== null) params.set("min", filters.rating_min);
  if (filters.rating_max !== null) params.set("max", filters.rating_max);
  if (filters.theme) params.set("theme", filters.theme);
  const text = params.toString();
  return text ? `?${text}` : "";
}

/** Fetch a random matching puzzle and open it. */
export async function openRandomLibraryPuzzle(filters, exclude = null) {
  let puzzle;
  try {
    puzzle = await api.libraryRandom({ ...filters, exclude });
  } catch (error) {
    if (error.status === 404) {
      throw new Error(exclude ? "No other puzzle matches these filters. Go back and widen them." : "No puzzle matches these filters. Try another difficulty or theme.");
    }
    throw error;
  }
  location.hash = `#/puzzles/lichess/${encodeURIComponent(puzzle.id)}${filterQuery(filters)}`;
}

/** "French_Defense_Tarrasch_Variation" -> "French Defense: Tarrasch Variation" */
function openingName(tags) {
  if (!tags.length) return null;
  const family = tags[0].replaceAll("_", " ");
  const variation = tags.length > 1 ? tags[tags.length - 1].replaceAll("_", " ").replace(family, "").trim() : "";
  return variation ? `${family}: ${variation}` : family;
}

export async function renderLibraryPuzzle(container, context, puzzleId) {
  const filters = libraryFilters(context.query);
  const puzzle = await api.libraryPuzzle(puzzleId);
  const userSteps = puzzle.solution.filter((step) => step.by === "user").length;
  const opening = openingName(puzzle.opening_tags);
  const themes = () => h("span", { class: "chips" }, puzzle.themes.map((t) => chip(themeLabel(t))));

  return mountTrainer(container, {
    historyKey: LIBRARY_PREFIX + puzzle.id,
    userId: context.user.id,
    fen: puzzle.fen,
    setup: puzzle.setup,
    userColor: puzzle.user_color,
    solution: puzzle.solution,
    title: "Lichess puzzle",
    subtitle: `Rated ${puzzle.rating}${filters.theme ? ` · ${themeLabel(filters.theme)}` : ""}`,
    back: { href: "#/puzzles?source=lichess", label: "← Lichess puzzles" },
    prevHref: null,
    onNext: () => openRandomLibraryPuzzle(filters, puzzle.id),
    firstTryText: "No hints and no wrong moves.",
    result: () =>
      h(
        "div",
        { class: "result-card" },
        h("p", {}, `Rated ${puzzle.rating} by Lichess players, who have played it ${puzzle.nb_plays.toLocaleString()} times. Its themes are now shown below.`),
      ),
    finishedLinks: () =>
      button("View on Lichess", {
        icon: "arrow",
        href: `https://lichess.org/training/${encodeURIComponent(puzzle.id)}`,
        target: "_blank",
        rel: "noopener noreferrer",
      }),
    facts: (finished) => [
      ["Source", h("a", { href: puzzle.game_url, target: "_blank", rel: "noopener noreferrer" }, "Lichess game ↗")],
      ["Rating", `${puzzle.rating} ± ${puzzle.rating_deviation}`],
      ["Length", `${plural(userSteps, "move")} to find`],
      ...(opening ? [["Opening", opening]] : []),
      // Themes name the tactic, so they would give the answer away.
      ["Themes", finished ? themes() : h("span", { class: "muted" }, "Shown when you finish")],
    ],
  });
}
