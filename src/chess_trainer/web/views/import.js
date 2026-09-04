// Welcome (choose or create a profile) and the Import page.

import { api } from "../api.js";
import { append, clear, formatDate, h } from "../dom.js";
import { jobs } from "../jobs.js";
import { PLATFORM_LABEL, button, emptyState, notice, pageHeader, panel, platformBadge, select } from "../ui.js";

const TIME_CLASSES = ["bullet", "blitz", "rapid", "classical", "correspondence"];
const COUNTS = [10, 20, 50, 100, 200];

function platformSelect() {
  return h(
    "select",
    { class: "select", "aria-label": "Chess site" },
    Object.entries(PLATFORM_LABEL).map(([value, label]) => h("option", { value }, label)),
  );
}

/** Run an async form action with a busy button and an inline error message. */
function guarded(submit, errorBox, action) {
  return async (event) => {
    event.preventDefault();
    errorBox.hidden = true;
    submit.disabled = true;
    try {
      await action();
    } catch (error) {
      errorBox.textContent = error.message;
      errorBox.hidden = false;
    } finally {
      submit.disabled = false;
    }
  };
}

// --- Welcome -------------------------------------------------------------------

export async function renderWelcome(container, context) {
  const users = await api.listUsers();
  const error = notice("", "error");
  error.hidden = true;
  const name = h("input", { class: "input", type: "text", placeholder: "Your name", required: true, maxLength: 100, autocomplete: "off" });
  const platform = platformSelect();
  const username = h("input", { class: "input", type: "text", placeholder: "Username on that site", maxLength: 100, autocomplete: "off" });
  const submit = button("Get started", { variant: "primary", type: "submit" });

  const create = guarded(submit, error, async () => {
    const user = await api.createUser(name.value.trim());
    await context.setUser(user.id);
    if (username.value.trim()) {
      // Link and import in one step so a new profile lands on real data.
      const account = await api.linkAccount(user.id, platform.value, username.value.trim());
      const { job_id: jobId } = await api.importGames(account.id, { max_games: 20 });
      await context.refreshUser();
      jobs.watch(jobId);
    }
    context.navigate("#/");
  });

  append(
    container,
    h(
      "div",
      { class: "welcome" },
      h("img", { class: "welcome-mark", src: "pieces/wN.svg", alt: "", width: 72, height: 72 }),
      h("h1", {}, "Chess Trainer"),
      h("p", { class: "welcome-tagline" }, "Find the mistakes you keep making, and practice the positions where you made them."),
      users.length
        ? panel(
            "Continue as",
            h(
              "div",
              { class: "profile-list" },
              users.map((user) =>
                h(
                  "button",
                  {
                    class: "profile",
                    type: "button",
                    onclick: async () => {
                      await context.setUser(user.id);
                      context.navigate("#/");
                    },
                  },
                  h("span", { class: "avatar", "aria-hidden": "true" }, user.display_name.slice(0, 1).toUpperCase()),
                  h("span", {}, user.display_name),
                  h("span", { class: "muted" }, `${user.accounts.length} linked`),
                ),
              ),
            ),
          )
        : null,
      panel(
        users.length ? "New profile" : "Create your profile",
        h(
          "form",
          { class: "form", onsubmit: create },
          h("label", { class: "field" }, h("span", {}, "Name"), name),
          h(
            "div",
            { class: "field" },
            h("span", {}, "Where do you play? (optional, you can add it later)"),
            h("div", { class: "field-row" }, platform, username),
          ),
          error,
          submit,
        ),
      ),
    ),
  );
}

// --- Import --------------------------------------------------------------------

export function addAccountForm(context, { importAfter = true } = {}) {
  const error = notice("", "error");
  error.hidden = true;
  const platform = platformSelect();
  const username = h("input", { class: "input", type: "text", placeholder: "Username", required: true, maxLength: 100, autocomplete: "off" });
  const submit = button(importAfter ? "Link and import" : "Link account", { variant: "primary", type: "submit" });
  return h(
    "form",
    {
      class: "form",
      onsubmit: guarded(submit, error, async () => {
        const account = await api.linkAccount(context.user.id, platform.value, username.value.trim());
        await context.refreshUser();
        if (importAfter) {
          const { job_id: jobId } = await api.importGames(account.id, { max_games: 20 });
          jobs.watch(jobId);
        }
        context.navigate(location.hash || "#/");
      }),
    },
    h("div", { class: "field-row" }, platform, username, submit),
    error,
  );
}

function accountRow(account) {
  const error = notice("", "error");
  error.hidden = true;
  let count = 20;
  const chosen = new Set();
  const toggles = TIME_CLASSES.map((name) =>
    h(
      "button",
      {
        class: "toggle",
        type: "button",
        "aria-pressed": "false",
        onclick: (event) => {
          if (chosen.has(name)) chosen.delete(name);
          else chosen.add(name);
          event.currentTarget.setAttribute("aria-pressed", String(chosen.has(name)));
        },
      },
      name,
    ),
  );
  const submit = button("Import and analyze", { variant: "primary", icon: "import", type: "submit" });
  return h(
    "form",
    {
      class: "account",
      onsubmit: guarded(submit, error, async () => {
        const { job_id: jobId } = await api.importGames(account.id, {
          max_games: count,
          time_classes: chosen.size ? [...chosen] : null,
        });
        jobs.watch(jobId);
      }),
    },
    h(
      "div",
      { class: "account-head" },
      platformBadge(account.platform),
      h("strong", {}, account.username),
      h("span", { class: "muted" }, account.last_synced_at ? `Last import ${formatDate(account.last_synced_at)}` : "Never imported"),
    ),
    h(
      "div",
      { class: "account-controls" },
      h(
        "label",
        { class: "field-inline" },
        h("span", {}, "Most recent"),
        select(COUNTS.map((n) => [String(n), `${n} games`]), "20", (value) => (count = Number(value)), "How many games"),
      ),
      h("div", { class: "field-inline" }, h("span", {}, "Only"), h("div", { class: "toggle-group" }, toggles)),
      submit,
    ),
    h("p", { class: "muted small" }, "Leave the time controls unselected to import everything. Games you already have are skipped."),
    error,
  );
}

export async function renderImport(container, context) {
  const accounts = context.user.accounts;
  append(
    container,
    pageHeader("Import games", "Pull in your recent games. Each one is analyzed move by move, and your mistakes become puzzles."),
    accounts.length
      ? panel("Your accounts", h("div", { class: "account-list" }, accounts.map(accountRow)))
      : emptyState({
          iconName: "import",
          title: "Link your first account",
          text: "Enter your Lichess or Chess.com username below. Only public games are read; no password is needed.",
        }),
    panel(accounts.length ? "Link another account" : "Link an account", addAccountForm(context, { importAfter: !accounts.length })),
    panel(
      "What happens next",
      h(
        "ol",
        { class: "steps" },
        h("li", {}, h("span", {}, h("strong", {}, "Fetch. "), "Your recent games are downloaded from the site.")),
        h("li", {}, h("span", {}, h("strong", {}, "Analyze. "), "Stockfish evaluates every position. This takes roughly a minute per game.")),
        h("li", {}, h("span", {}, h("strong", {}, "Train. "), "Mistakes with one clearly best answer turn into puzzles.")),
      ),
      h("p", { class: "muted small" }, "Progress appears at the top of every page, and you can keep browsing while it runs."),
    ),
  );
}
