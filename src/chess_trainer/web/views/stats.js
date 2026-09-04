// Performance: accuracy, move quality, and where the errors come from.

import { api } from "../api.js";
import { meter, stackedBar, trendChart } from "../charts.js";
import { append, clear, formatDate, h, plural, titleCase } from "../dom.js";
import { buildInsights } from "../insights.js";
import { button, emptyState, opponentOf, pageHeader, panel, select, statTile } from "../ui.js";

const TIME_CLASSES = ["bullet", "blitz", "rapid", "classical", "correspondence"];
const PRESSURE_LABEL = { under_pressure: "Low on time", not_under_pressure: "Enough time" };
const MIN_TREND_GAMES = 3;

export async function renderStats(container, context) {
  const user = context.user;
  const body = h("div", { class: "stack" });
  const filters = { time_class: "", account_id: "" };

  const load = async () => {
    const [report, games] = await Promise.all([
      api.report(user.id, filters),
      api.userGames(user.id, { account_id: filters.account_id, limit: 200 }),
    ]);
    const analyzed = games.filter((row) => row.stats && (!filters.time_class || row.game.time_class === filters.time_class));
    clear(body);
    append(body, statsBody(report, analyzed, Boolean(filters.time_class || filters.account_id)));
  };
  const change = (key) => (value) => {
    filters[key] = value;
    load();
  };

  append(
    container,
    pageHeader(
      "Stats",
      "How accurately you play, and where your errors come from.",
      select([["", "All time controls"], ...TIME_CLASSES.map((t) => [t, titleCase(t)])], "", change("time_class"), "Time control"),
      user.accounts.length > 1
        ? select([["", "All accounts"], ...user.accounts.map((a) => [String(a.id), `${a.username} (${a.platform})`])], "", change("account_id"), "Account")
        : null,
    ),
    body,
  );
  await load();
}

function statsBody(report, games, filtered) {
  if (!report.games_analyzed) {
    return emptyState({
      iconName: "stats",
      title: filtered ? "No analyzed games match these filters" : "No statistics yet",
      text: filtered ? "Try a different time control or account." : "Statistics appear once your games have been imported and analyzed.",
      action: filtered ? null : button("Import games", { variant: "primary", icon: "import", href: "#/import" }),
    });
  }
  const overall = report.overall;
  const good = overall.moves - overall.inaccuracies - overall.mistakes - overall.blunders;
  const insights = buildInsights(report);
  return [
    h(
      "div",
      { class: "stat-row" },
      statTile("Accuracy", `${overall.accuracy}%`, "Average over your moves"),
      statTile("Games analyzed", report.games_analyzed, `${overall.moves} of your moves`),
      statTile("Errors per 100 moves", overall.errors_per_100_moves, "Mistakes and blunders"),
      statTile("Average loss per move", `${overall.average_win_pct_loss}%`, "Winning chances given away"),
    ),
    insights.length
      ? panel(
          "Key findings",
          h("ul", { class: "insights" }, insights.map((item) => h("li", { class: "insight" }, h("div", {}, h("strong", {}, item.title), h("p", { class: "muted" }, item.text))))),
        )
      : null,
    h(
      "div",
      { class: "two-col" },
      panel(
        "Move quality",
        stackedBar([
          { label: "Good", value: good, kind: "good" },
          { label: "Inaccuracies", value: overall.inaccuracies, kind: "inaccuracy" },
          { label: "Mistakes", value: overall.mistakes, kind: "mistake" },
          { label: "Blunders", value: overall.blunders, kind: "blunder" },
        ]),
      ),
      panel("Accuracy by game", accuracyTrend(games)),
    ),
    h(
      "div",
      { class: "two-col" },
      panel("By game phase", bucketTable("Phase", report.by_phase, titleCase)),
      panel(
        "By time on the clock",
        report.by_time_pressure.length
          ? bucketTable("Clock", report.by_time_pressure, (key) => PRESSURE_LABEL[key] || titleCase(key))
          : h("p", { class: "muted" }, "These games have no clock data."),
        h("p", { class: "muted small" }, "Low on time means under 30 seconds, or under 10% of the starting time in faster games."),
      ),
    ),
    panel("By opening", bucketTable("Opening", report.by_opening, (key) => key, true)),
    Object.keys(report.by_motif).length
      ? panel(
          "Tactical themes in your puzzles",
          h("ul", { class: "legend" }, Object.entries(report.by_motif).map(([name, count]) => h("li", {}, h("span", { class: "legend-label" }, titleCase(name)), h("strong", {}, count)))),
        )
      : null,
  ];
}

function accuracyTrend(games) {
  if (games.length < MIN_TREND_GAMES) {
    return h("p", { class: "muted" }, `A trend needs at least ${MIN_TREND_GAMES} analyzed games. You have ${games.length}.`);
  }
  const oldestFirst = [...games].reverse().slice(-30);
  const items = oldestFirst.map((row) => ({
    value: row.stats.accuracy,
    label: `${formatDate(row.game.played_at)} vs ${opponentOf(row).name}`,
  }));
  const average = (rows) => rows.reduce((sum, item) => sum + item.value, 0) / rows.length;
  const half = Math.floor(items.length / 2);
  const change = average(items.slice(half)) - average(items.slice(0, half));
  const direction = Math.abs(change) < 1.5 ? "Steady" : change > 0 ? `Up ${change.toFixed(1)} points` : `Down ${Math.abs(change).toFixed(1)} points`;
  return [
    trendChart(items),
    h("p", { class: "muted small" }, `Your last ${plural(items.length, "game")}, oldest to newest. ${direction} between the first and second half.`),
  ];
}

function bucketTable(firstColumn, buckets, labelOf, showMoves = false) {
  if (!buckets.length) return h("p", { class: "muted" }, "Nothing to show yet.");
  const worst = Math.max(...buckets.map((b) => b.stats.errors_per_100_moves), 1);
  return h(
    "div",
    { class: "table-scroll" },
    h(
      "table",
      { class: "table" },
      h(
        "thead",
        {},
        h(
          "tr",
          {},
          h("th", {}, firstColumn),
          h("th", { class: "num" }, "Moves"),
          h("th", { class: "num" }, "Accuracy"),
          showMoves ? h("th", { class: "num hide-sm" }, "Blunders") : null,
          h("th", {}, "Errors per 100 moves"),
        ),
      ),
      h(
        "tbody",
        {},
        buckets.map(({ key, stats }) =>
          h(
            "tr",
            {},
            h("td", {}, labelOf(key)),
            h("td", { class: "num" }, stats.moves),
            h("td", { class: "num" }, `${stats.accuracy}%`),
            showMoves ? h("td", { class: "num hide-sm" }, stats.blunders) : null,
            h("td", { class: "meter-cell" }, meter(stats.errors_per_100_moves, worst)),
          ),
        ),
      ),
    ),
  );
}
