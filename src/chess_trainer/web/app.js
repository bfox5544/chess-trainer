// Entry point: app shell (navigation), hash router, and "who am I" state.
// There is no login yet, so the chosen profile is just remembered locally.

import { api } from "./api.js";
import { append, clear, h } from "./dom.js";
import { icon } from "./icons.js";
import { jobs, renderJobBanner } from "./jobs.js";
import { sound } from "./sounds.js";
import { button, loading, notice } from "./ui.js";
import { renderDashboard } from "./views/dashboard.js";
import { renderGame } from "./views/game.js";
import { renderGames } from "./views/games.js";
import { renderImport, renderWelcome } from "./views/import.js";
import { renderLibraryPuzzle } from "./views/library-puzzle.js";
import { renderOpening } from "./views/opening.js";
import { renderPuzzle } from "./views/puzzle.js";
import { renderPuzzles } from "./views/puzzles.js";
import { renderRepeated } from "./views/repeated.js";
import { renderStats } from "./views/stats.js";

const USER_KEY = "chessTrainer.userId";
const NAV = [
  { route: "", label: "Home", icon: "home" },
  { route: "games", label: "Analysis", icon: "games" },
  { route: "puzzles", label: "Puzzles", icon: "puzzle" },
  { route: "stats", label: "Stats", icon: "stats" },
];
const ROUTES = {
  "": renderDashboard,
  games: (el, ctx, id, extra) => (id ? renderGame(el, ctx, id, extra) : renderGames(el, ctx)),
  puzzles: (el, ctx, id, extra) =>
    id === "lichess" && extra ? renderLibraryPuzzle(el, ctx, extra) : id ? renderPuzzle(el, ctx, id) : renderPuzzles(el, ctx),
  stats: (el, ctx, id) => (id === "opening" ? renderOpening(el, ctx) : id === "repeated" ? renderRepeated(el, ctx) : renderStats(el, ctx)),
  report: renderStats, // old link
  import: renderImport,
};

const shell = document.getElementById("shell");
const view = document.getElementById("view");
const sidebar = document.getElementById("sidebar");
const tabbar = document.getElementById("tabbar");
const banner = document.getElementById("job-banner");
let cleanup = null; // the current view's teardown (timers, key handlers)
let renderToken = 0;

function storedUserId() {
  const fromUrl = new URLSearchParams(location.search).get("user"); // ?user=3 makes views linkable
  try {
    return fromUrl || localStorage.getItem(USER_KEY);
  } catch {
    return fromUrl;
  }
}

const context = {
  user: null,
  query: {},
  async setUser(userId) {
    try {
      if (userId) localStorage.setItem(USER_KEY, String(userId));
      else localStorage.removeItem(USER_KEY);
    } catch {
      /* storage unavailable: the choice just won't persist */
    }
    context.user = userId ? await api.getUser(userId) : null;
    renderNav();
  },
  async refreshUser() {
    if (context.user) context.user = await api.getUser(context.user.id);
  },
  navigate(hash) {
    if (location.hash === hash) route();
    else location.hash = hash;
  },
};

function currentSection() {
  return location.hash.replace(/^#\/?/, "").split("?")[0].split("/")[0];
}

function navLink({ route: name, label, icon: iconName }, section) {
  const active = section === name || (name === "stats" && section === "report");
  return h(
    "a",
    { class: "nav-link", href: `#/${name}`, "aria-current": active ? "page" : null },
    icon(iconName),
    h("span", {}, label),
  );
}

/** Turns move sounds on or off; styled like a nav link so it sits in both menus. */
function soundToggle({ compact = false } = {}) {
  const label = h("span");
  const glyph = h("span", { class: "nav-icon" });
  const toggle = h("button", { class: "nav-link sound-toggle", type: "button", onclick: () => sound.toggle() }, glyph, label);
  const show = (on) => {
    clear(glyph).append(icon(on ? "sound" : "muted"));
    clear(label).append(compact ? "Sound" : on ? "Sound on" : "Sound off");
    toggle.setAttribute("aria-pressed", String(on));
    toggle.title = on ? "Move sounds are on; click to mute" : "Move sounds are off; click to turn them on";
  };
  show(sound.enabled);
  // Both copies (sidebar and tab bar) stay in step; a copy dropped by the
  // next renderNav unsubscribes itself.
  const stop = sound.subscribe((on) => (toggle.isConnected ? show(on) : stop()));
  return toggle;
}

function renderNav() {
  const section = currentSection();
  shell.classList.toggle("no-user", !context.user);
  clear(sidebar);
  clear(tabbar);
  if (!context.user) return;
  append(
    sidebar,
    h("a", { class: "brand", href: "#/" }, h("img", { src: "pieces/wN.svg", alt: "", width: 30, height: 30 }), "Chess Trainer"),
    h("nav", { class: "nav" }, NAV.map((item) => navLink(item, section))),
    button("Import games", { variant: "primary", icon: "import", href: "#/import", class: "btn btn-primary sidebar-cta" }),
    soundToggle(),
    h(
      "div",
      { class: "sidebar-user" },
      h("span", { class: "avatar", "aria-hidden": "true" }, context.user.display_name.slice(0, 1).toUpperCase()),
      h(
        "div",
        {},
        h("div", { class: "sidebar-user-name" }, context.user.display_name),
        h(
          "button",
          {
            class: "link",
            type: "button",
            onclick: async () => {
              await context.setUser(null);
              context.navigate("#/");
            },
          },
          "Switch profile",
        ),
      ),
    ),
  );
  append(
    tabbar,
    NAV.map((item) => navLink(item, section)),
    navLink({ route: "import", label: "Import", icon: "import" }, section),
    soundToggle({ compact: true }), // the icon shows on or off
  );
}

async function route() {
  const [path, queryText = ""] = location.hash.replace(/^#\/?/, "").split("?");
  const [section = "", id, extra] = path.split("/");
  context.query = Object.fromEntries(new URLSearchParams(queryText));
  const token = ++renderToken;
  if (cleanup) cleanup();
  cleanup = null;
  renderNav();
  clear(view).append(loading());

  const render = context.user ? ROUTES[section] || renderDashboard : renderWelcome;
  const container = h("div", { class: `page page-${context.user ? section || "home" : "welcome"}` });
  try {
    const teardown = await render(container, context, id, extra);
    if (token !== renderToken) {
      if (typeof teardown === "function") teardown(); // user navigated away meanwhile
      return;
    }
    clear(view).append(container);
    cleanup = typeof teardown === "function" ? teardown : null;
    window.scrollTo(0, 0);
  } catch (error) {
    if (token !== renderToken) return;
    clear(view).append(
      h(
        "div",
        { class: "page" },
        notice(error.message || "Something went wrong.", "error"),
        button("Try again", { onclick: route }),
      ),
    );
  }
}

// Pages whose content changes when an import/analysis job finishes.
const REFRESH_ON_JOB = ["", "games", "puzzles", "stats", "report", "import"];

jobs.subscribe((state, event) => {
  renderJobBanner(banner);
  const onListPage = REFRESH_ON_JOB.includes(currentSection()) && !location.hash.match(/^#\/(games|puzzles|stats)\/[^?]/);
  if (event === "finished" && context.user && onListPage) route();
});

// Linked accounts are synced by the worker on a timer. Look for an import
// whose new games are being analyzed, and follow it in the banner.
const SYNC_CHECK_MS = 60_000;
async function followSync() {
  if (!context.user || jobs.active || document.hidden) return;
  try {
    const { active_job_id: jobId } = await api.syncStatus(context.user.id);
    if (jobId && !jobs.active && jobId !== jobs.dismissedId) jobs.watch(jobId);
  } catch {
    /* server unreachable: try again next time */
  }
}

async function start() {
  const userId = storedUserId();
  if (userId) {
    try {
      await context.setUser(userId);
    } catch {
      await context.setUser(null); // remembered profile no longer exists
    }
  }
  window.addEventListener("hashchange", route);
  jobs.resume();
  route();
  followSync();
  setInterval(followSync, SYNC_CHECK_MS);
  document.addEventListener("visibilitychange", followSync);
}

start();
