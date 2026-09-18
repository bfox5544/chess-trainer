// Tracks the current background job (a game import with its analysis, or a
// load of the Lichess puzzle database) across pages and renders its banner.

import { api } from "./api.js";
import { append, clear, h, plural } from "./dom.js";
import { icon } from "./icons.js";
import { button, spinner } from "./ui.js";

const JOB_KEY = "chessTrainer.jobId";
const POLL_MS = 1500;
const STUCK_AFTER_MS = 6000;
const FINISHED = ["succeeded", "failed"];

const listeners = new Set();
let timer = null;
let queuedSince = null;
let state = null; // { job, analysis, done, stuck }
let dismissedId = null; // a job closed by the user is not picked up again

function remember(jobId) {
  try {
    if (jobId) localStorage.setItem(JOB_KEY, String(jobId));
    else localStorage.removeItem(JOB_KEY);
  } catch {
    /* storage unavailable */
  }
}

function emit(event) {
  for (const listener of listeners) listener(state, event);
}

async function poll(jobId) {
  let job;
  try {
    job = await api.job(jobId);
  } catch (error) {
    if (error.status === 404) return jobs.dismiss();
    timer = setTimeout(() => poll(jobId), POLL_MS * 2); // server briefly unreachable
    return;
  }
  const analysis = job.children[0] || null;
  const done =
    job.status === "failed" || (job.status === "succeeded" && (!analysis || FINISHED.includes(analysis.status)));
  const waiting = job.status === "queued" || analysis?.status === "queued";
  queuedSince = waiting ? queuedSince || Date.now() : null;
  const wasDone = state?.done;
  state = { job, analysis, done, stuck: Boolean(queuedSince && Date.now() - queuedSince > STUCK_AFTER_MS) };
  emit(done && !wasDone ? "finished" : "progress");
  if (!done) timer = setTimeout(() => poll(jobId), POLL_MS);
}

export const jobs = {
  /** Start following a job that was just queued. */
  watch(jobId) {
    clearTimeout(timer);
    queuedSince = null;
    state = null;
    remember(jobId);
    poll(jobId);
  },
  /** Pick up a job from a previous page load, if any. */
  resume() {
    let jobId = null;
    try {
      jobId = localStorage.getItem(JOB_KEY);
    } catch {
      /* ignore */
    }
    if (jobId) poll(jobId);
  },
  dismiss() {
    clearTimeout(timer);
    if (state) dismissedId = state.job.id;
    state = null;
    remember(null);
    emit("dismissed");
  },
  get dismissedId() {
    return dismissedId;
  },
  get active() {
    return Boolean(state && !state.done);
  },
  subscribe(listener) {
    listeners.add(listener);
    return () => listeners.delete(listener);
  },
};

// --- presentation --------------------------------------------------------------

function failureText(error, what) {
  const message = String(error || "");
  if (message.startsWith("PlayerNotFound")) {
    return "We couldn't find that username. Check the spelling on the Import page and try again.";
  }
  if (message.startsWith("RateLimited")) {
    return "The chess site is limiting requests right now. Wait a few minutes and try again.";
  }
  if (message.startsWith("SourceUnavailable")) {
    return what === "puzzle download"
      ? "The download from database.lichess.org failed. Puzzles stored before the failure are kept; try again to continue."
      : "The chess site isn't responding right now. Try again in a little while.";
  }
  return `The ${what} didn't finish. Try again; if it keeps failing, check the worker's log.`;
}

function describeLibrary({ job, stuck }) {
  if (job.status === "failed") return { kind: "error", title: "Loading puzzles failed", text: failureText(job.error, "puzzle download") };
  if (job.status === "succeeded") {
    const stored = job.result?.stored ?? 0;
    return { kind: "done", title: `${stored.toLocaleString()} Lichess puzzles loaded`, text: "Pick a difficulty on the Puzzles page and start solving." };
  }
  if (job.status === "queued") {
    return { kind: "busy", title: "Waiting to load Lichess puzzles…", text: stuck ? null : "It starts once the worker is free." };
  }
  const total = job.progress_total;
  return {
    kind: "busy",
    title: `Loading Lichess puzzles: ${job.progress_done.toLocaleString()}${total ? ` of ${total.toLocaleString()}` : ""}`,
    text: "Downloading from database.lichess.org; you can keep using the app.",
    progress: total ? [job.progress_done, total] : null,
  };
}

function describe(state) {
  if (state.job.kind === "puzzle_library") return describeLibrary(state);
  const { job, analysis, stuck } = state;
  if (job.status === "failed") return { kind: "error", title: "Import failed", text: failureText(job.error, "import") };
  if (job.status !== "succeeded") {
    return { kind: "busy", title: "Fetching your games…", text: stuck ? null : "This usually takes a few seconds." };
  }
  const result = job.result || {};
  const fetched = `${plural(result.stored ?? 0, "new game")} imported`;
  if (!analysis) return { kind: "done", title: fetched, text: "Analysis was not requested." };
  if (analysis.status === "failed") {
    return { kind: "error", title: "Analysis failed", text: failureText(analysis.error, "analysis") };
  }
  if (analysis.status === "succeeded") {
    const done = analysis.result || {};
    const failed = Object.keys(done.failed || {}).length;
    return {
      kind: "done",
      title: done.analyzed ? `${plural(done.analyzed, "game")} analyzed` : "You're up to date",
      text:
        (done.analyzed
          ? `${fetched}. ${plural(done.puzzles_created ?? 0, "new puzzle")} from your mistakes.`
          : "No new games to analyze.") + (failed ? ` ${plural(failed, "game")} could not be analyzed.` : ""),
    };
  }
  const total = analysis.progress_total;
  if (analysis.status === "queued" || total === null) {
    return { kind: "busy", title: "Waiting for the analysis to start…", text: `${fetched}.` };
  }
  return {
    kind: "busy",
    title: `Analyzing game ${Math.min(analysis.progress_done + 1, total)} of ${total}`,
    text: `${fetched}. Stockfish is checking every move; you can keep using the app.`,
    progress: [analysis.progress_done, total],
  };
}

export function renderJobBanner(container) {
  clear(container);
  if (!state) return;
  const view = describe(state);
  const lead =
    view.kind === "busy" ? spinner() : h("span", { class: `banner-icon ${view.kind}` }, icon(view.kind === "done" ? "check" : "alert", 18));
  const banner = h(
    "div",
    { class: `banner banner-${view.kind}` },
    lead,
    h(
      "div",
      { class: "banner-body" },
      h("strong", {}, view.title),
      view.text ? h("span", { class: "muted" }, view.text) : null,
      view.progress ? h("progress", { max: view.progress[1], value: view.progress[0] }) : null,
      state.stuck
        ? h(
            "span",
            { class: "banner-warn" },
            "Nothing is picking this up. Start the worker in a terminal: ",
            h("code", {}, "uv run chess-trainer-worker"),
          )
        : null,
    ),
    view.kind === "busy" ? null : button("", { icon: "close", variant: "ghost", "aria-label": "Dismiss", onclick: () => jobs.dismiss() }),
  );
  append(container, banner);
}
