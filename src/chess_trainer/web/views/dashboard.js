// Home: how you're doing, what to work on, and where to go next.

import { api } from "../api.js";
import { miniBoard } from "../board.js";
import { append, formatDate, h, plural, titleCase } from "../dom.js";
import { isSolved, loadHistory } from "../history.js";
import { buildInsights } from "../insights.js";
import { jobs } from "../jobs.js";
import { button, colorDot, emptyState, opponentOf, pageHeader, panel, resultPill, statTile } from "../ui.js";
import { addAccountForm } from "./import.js";

export async function renderDashboard(container, context) {
  const user = context.user;
  if (!user.accounts.length) {
    append(
      container,
      pageHeader(`Welcome, ${user.display_name}`),
      emptyState({
        iconName: "import",
        title: "Link an account to get started",
        text: "Enter your Lichess or Chess.com username. Your 20 most recent games are imported and analyzed right away.",
        action: addAccountForm(context),
      }),
    );
    return;
  }

  const [report, games, puzzles] = await Promise.all([
    api.report(user.id),
    api.userGames(user.id, { limit: 6 }),
    api.puzzles(user.id),
  ]);
  const history = loadHistory(user.id);
  const unsolved = puzzles.filter((p) => !isSolved(history, p.id));

  append(
    container,
    pageHeader(
      `Welcome back, ${user.display_name}`,
      report.games_analyzed ? `Based on ${plural(report.games_analyzed, "analyzed game")}.` : null,
      button("Import games", { icon: "import", href: "#/import" }),
    ),
  );

  if (!games.length) {
    append(
      container,
      emptyState({
        iconName: "import",
        title: jobs.active ? "Your games are on their way" : "No games yet",
        text: jobs.active
          ? "This page fills in as soon as the import finishes."
          : "Import your recent games to see your accuracy, your weak spots, and puzzles from your own mistakes.",
        action: jobs.active ? null : button("Import games", { variant: "primary", icon: "import", href: "#/import" }),
      }),
    );
    return;
  }

  if (!report.games_analyzed) {
    append(
      container,
      emptyState({
        iconName: "clock",
        title: jobs.active ? "Analyzing your games…" : "Your games haven't been analyzed yet",
        text: jobs.active
          ? "Stockfish is working through them. Statistics and puzzles appear here when it finishes."
          : "Start an import to analyze them. Make sure the worker is running.",
        action: jobs.active ? null : button("Go to import", { variant: "primary", href: "#/import" }),
      }),
      recentGames(games),
    );
    return;
  }

  const overall = report.overall;
  append(
    container,
    h(
      "div",
      { class: "stat-row" },
      statTile("Accuracy", `${overall.accuracy}%`, "Average over your moves"),
      statTile("Games analyzed", report.games_analyzed),
      statTile("Errors per 100 moves", overall.errors_per_100_moves, `${plural(overall.mistakes, "mistake")}, ${plural(overall.blunders, "blunder")}`),
      statTile("Puzzles to solve", unsolved.length, puzzles.length ? `${puzzles.length - unsolved.length} of ${puzzles.length} solved` : "None yet"),
    ),
    h(
      "div",
      { class: "home-grid" },
      h("div", { class: "home-main" }, focusAreas(report), recentGames(games)),
      h("div", { class: "home-side" }, trainingCard(puzzles, unsolved)),
    ),
  );
}

function focusAreas(report) {
  const insights = buildInsights(report);
  if (!insights.length) {
    return panel(
      "What to work on",
      h("p", { class: "muted" }, "No clear pattern yet. Patterns need a few more analyzed games; import more to sharpen this."),
    );
  }
  return panel(
    "What to work on",
    h(
      "ul",
      { class: "insights" },
      insights.map((item) =>
        h(
          "li",
          { class: "insight" },
          h("div", {}, h("strong", {}, item.title), h("p", { class: "muted" }, item.text)),
          h("a", { class: "insight-link", href: item.href }, item.action),
        ),
      ),
    ),
  );
}

function recentGames(games) {
  return panel(
    "Recent games",
    h(
      "ul",
      { class: "game-list" },
      games.map((row) => {
        const opponent = opponentOf(row);
        const stats = row.stats;
        return h(
          "li",
          {},
          h(
            "a",
            { class: "game-row", href: `#/games/${row.game.id}` },
            resultPill(row.outcome),
            h(
              "div",
              { class: "game-row-main" },
              h("div", {}, colorDot(row.user_color), " vs ", h("strong", {}, opponent.name), opponent.rating ? ` (${opponent.rating})` : ""),
              h("div", { class: "muted small" }, [row.game.opening_name, titleCase(row.game.time_class), formatDate(row.game.played_at)].filter(Boolean).join(" · ")),
            ),
            stats
              ? h(
                  "div",
                  { class: "game-row-stats" },
                  h("strong", {}, `${stats.accuracy}%`),
                  h("span", { class: "muted small" }, stats.mistakes + stats.blunders ? plural(stats.mistakes + stats.blunders, "error") : "No errors"),
                )
              : h("div", { class: "game-row-stats muted small" }, "Not analyzed"),
          ),
        );
      }),
    ),
    h("a", { class: "panel-more", href: "#/games" }, "All games"),
  );
}

function trainingCard(puzzles, unsolved) {
  if (!puzzles.length) {
    return panel(
      "Training",
      h("p", { class: "muted" }, "No puzzles yet. They are made from mistakes that had one clearly best answer, so more analyzed games means more puzzles."),
    );
  }
  const next = unsolved[0] || puzzles[0];
  return panel(
    "Training",
    h("a", { class: "train-board", href: `#/puzzles/${next.id}`, "aria-label": "Open the next puzzle" }, miniBoard(next.fen, next.user_color)),
    h(
      "p",
      {},
      unsolved.length
        ? `${plural(unsolved.length, "puzzle")} from your own games waiting. ${titleCase(next.user_color)} to move in this one.`
        : "You've solved every puzzle. Replay them or import more games.",
    ),
    button(unsolved.length ? "Solve next puzzle" : "Replay puzzles", { variant: "primary", icon: "puzzle", href: `#/puzzles/${next.id}` }),
  );
}
