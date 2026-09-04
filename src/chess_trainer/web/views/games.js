// Analysis: every imported game, with how you did in it.

import { api } from "../api.js";
import { append, clear, formatDate, h, titleCase } from "../dom.js";
import { jobs } from "../jobs.js";
import { MOVE_KINDS, button, colorDot, emptyState, opponentOf, pageHeader, platformBadge, resultPill, select } from "../ui.js";

export async function renderGames(container, context) {
  const user = context.user;
  const list = h("div");
  let accountId = "";

  const load = async () => {
    const rows = await api.userGames(user.id, { account_id: accountId, limit: 200 });
    clear(list);
    if (!rows.length) {
      append(
        list,
        emptyState({
          iconName: "games",
          title: jobs.active ? "Importing your games…" : "No games here yet",
          text: "Imported games appear here with a move-by-move analysis.",
          action: jobs.active ? null : button("Import games", { variant: "primary", icon: "import", href: "#/import" }),
        }),
      );
      return;
    }
    append(list, gamesTable(rows, user.accounts));
  };

  append(
    container,
    pageHeader(
      "Game analysis",
      "Open a game to step through it and see where the evaluation turned.",
      user.accounts.length > 1
        ? select(
            [["", "All accounts"], ...user.accounts.map((a) => [String(a.id), `${a.username} (${a.platform})`])],
            "",
            (value) => {
              accountId = value;
              load();
            },
            "Account",
          )
        : null,
      button("Import games", { icon: "import", href: "#/import" }),
    ),
    list,
  );
  await load();
}

function gamesTable(rows, accounts) {
  const platformOf = Object.fromEntries(accounts.map((a) => [a.id, a.platform]));
  return h(
    "div",
    { class: "panel table-panel" },
    h(
      "table",
      { class: "table table-rows" },
      h(
        "thead",
        {},
        h(
          "tr",
          {},
          h("th", {}, "Result"),
          h("th", {}, "Opponent"),
          h("th", { class: "hide-sm" }, "Opening"),
          h("th", { class: "hide-md" }, "Played"),
          h("th", { class: "num" }, "Accuracy"),
          h("th", { class: "num" }, "Errors"),
        ),
      ),
      h(
        "tbody",
        {},
        rows.map((row) => {
          const opponent = opponentOf(row);
          const open = () => (location.hash = `#/games/${row.game.id}`);
          return h(
            "tr",
            {
              tabindex: 0,
              onclick: open,
              onkeydown: (event) => event.key === "Enter" && open(),
            },
            h("td", {}, resultPill(row.outcome)),
            h(
              "td",
              {},
              h("div", { class: "cell-main" }, colorDot(row.user_color), h("a", { href: `#/games/${row.game.id}` }, opponent.name), opponent.rating ? h("span", { class: "muted" }, opponent.rating) : null),
              h("div", { class: "muted small show-sm" }, row.game.opening_name || ""),
            ),
            h("td", { class: "hide-sm" }, row.game.opening_name || h("span", { class: "muted" }, "Unknown")),
            h(
              "td",
              { class: "hide-md nowrap" },
              h("div", {}, formatDate(row.game.played_at)),
              h("div", { class: "muted small" }, platformBadge(platformOf[row.account_id]), " ", titleCase(row.game.time_class)),
            ),
            h("td", { class: "num" }, row.stats ? h("strong", {}, `${row.stats.accuracy}%`) : h("span", { class: "muted" }, "Pending")),
            h("td", { class: "num" }, row.stats ? errorCounts(row.stats) : ""),
          );
        }),
      ),
    ),
  );
}

function errorCounts(stats) {
  const count = (kind, value) =>
    h(
      "span",
      { class: value ? `cls-${kind}` : "muted", title: MOVE_KINDS[kind].label },
      h("span", { "aria-hidden": "true" }, MOVE_KINDS[kind].symbol),
      ` ${value}`,
      h("span", { class: "sr-only" }, ` ${MOVE_KINDS[kind].label}`),
    );
  return h(
    "span",
    { class: "error-counts" },
    count("inaccuracy", stats.inaccuracies),
    count("mistake", stats.mistakes),
    count("blunder", stats.blunders),
  );
}
