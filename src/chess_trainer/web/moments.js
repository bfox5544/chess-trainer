// Key moments of a game: its few turning points as "find the move" exercises,
// played on the game page's own board (borrowed while an exercise runs, like
// playon.js). The API picks the moments (reports/key_moments.py).
//
// The move to find is the engine's choice; any other move the engine scores
// as good is accepted too. Your own move from the game is rejected without
// asking the engine when it was the mistake.

import { api } from "./api.js";
import { checkedKingSquare } from "./board.js";
import { append, clear, h, plural } from "./dom.js";
import { HIGHLIGHTS, button, kindBadge, moveKind, notice, reasonList } from "./ui.js";
import { Chess } from "./vendor/chess.js";

const RESET_DELAY_MS = 900;
const squaresOf = (uci) => (uci ? [uci.slice(0, 2), uci.slice(2, 4)] : []);
const arrowOf = (uci, kind) => ({ from: uci.slice(0, 2), to: uci.slice(2, 4), kind });
const moveLabel = (moment, san) => `${moment.move_number}${moment.color === "white" ? "." : "..."} ${san}`;

/** What to look for, without giving the answer away. */
function promptText(moment) {
  const side = moment.color === "white" ? "White" : "Black";
  const prompts = {
    mistake: "You went wrong here in the game. Find a better move.",
    missed: `Your opponent just slipped with ${moment.previous_san}. Find the move that makes them pay.`,
    punished: `Your opponent just played ${moment.previous_san}, a mistake. Find the punishment.`,
    great: "Only one move holds the position here. Find it.",
    brilliant: "There's a brilliant move here. Find it.",
  };
  return `${prompts[moment.kind] || "Find the best move."} ${side} to move.`;
}

/**
 * moments: the API's key_moments; moves: the game's moves (for each moment's badge).
 * onReview(ply): leave the exercises and show the game at `ply` (undefined: where it was).
 * onActive(active): called when exercises start and stop, so the page can hide its coach.
 * Returns { element, start(index), stop(silent), active() }.
 */
export function createKeyMoments({ board, moments, moves, onReview, onActive }) {
  const element = h("div", { class: "moments" });
  let at = -1; // index of the running exercise, -1 = overview
  let chess, selected, targets, lastMove, arrows, phase, borrowed, timer, run, found;
  run = 0;
  found = new Set();

  const badgeKind = (moment) => moveKind(moves.find((move) => move.ply === moment.ply) || { classification: "good" });

  function draw() {
    board.setPosition(chess.fen());
    board.setBadge(null);
    board.setArrows(arrows);
    board.setMarks({ selected, targets, lastMove, check: checkedKingSquare(chess) });
  }

  function overview() {
    clear(element);
    const rows = moments.map((moment, index) =>
      h(
        "button",
        { class: "moment-row", type: "button", onclick: () => start(index) },
        kindBadge(badgeKind(moment)),
        h("span", { class: "moment-move" }, moveLabel(moment, moment.played_san)),
        h("span", { class: "moment-title" }, moment.title),
        found.has(index) ? h("span", { class: "moment-found", title: "Found" }, "✓") : null,
      ),
    );
    append(
      element,
      h("p", { class: "muted" }, `${plural(moments.length, "turning point")} in this game. Find the right move at each, then see what happened.`),
      h("div", { class: "moment-list" }, rows),
      button(found.size ? "Review again" : "Start review", { variant: "primary", icon: "arrow", onclick: () => start(0) }),
    );
  }

  function header(moment) {
    return h(
      "div",
      { class: "coach-head" },
      h("strong", {}, `Key moment ${at + 1} of ${moments.length}`),
      h("span", { class: "muted small moment-progress" }, moment.previous_san ? `after ${moment.previous_san}` : ""),
    );
  }

  function controls(moment, revealed) {
    const last = at === moments.length - 1;
    return h(
      "div",
      { class: "moment-controls" },
      revealed
        ? [
            button(last ? "Finish" : "Next moment", { variant: "primary", icon: last ? "check" : "next", onclick: () => (last ? finish() : start(at + 1)) }),
            button("See it in the game", { icon: "eye", onclick: () => onReview(moment.ply) }),
          ]
        : [
            button("Show answer", { icon: "hint", onclick: () => reveal(moment, null) }),
            button(last ? "Skip" : "Skip to next", { variant: "ghost", icon: "skip", onclick: () => (last ? finish() : start(at + 1)) }),
          ],
      button("Back to the game", { variant: "ghost", onclick: () => stop() }),
    );
  }

  function ask(moment, ...extra) {
    clear(element);
    append(element, header(moment), h("p", {}, promptText(moment)), ...extra, controls(moment, false));
  }

  function start(index) {
    if (at < 0) {
      borrowed = { interactive: board.interactive, onSquare: board.onSquare };
      board.setInteractive(true, onSquare);
      onActive(true);
    }
    run += 1;
    clearTimeout(timer);
    at = index;
    const moment = moments[at];
    chess = new Chess(moment.fen);
    [selected, targets, lastMove, arrows, phase] = [null, [], squaresOf(moment.previous_uci), [], "asking"];
    draw();
    ask(moment);
  }

  /** `outcome`: null (answer shown), { san, alternative } for a good move found. */
  function reveal(moment, outcome) {
    run += 1;
    clearTimeout(timer);
    phase = "revealed";
    if (outcome) found.add(at);
    chess = new Chess(moment.fen);
    [selected, targets, lastMove] = [null, [], squaresOf(moment.previous_uci)];
    arrows = [arrowOf(moment.answer_uci, "best")];
    if (moment.played_uci !== moment.answer_uci) arrows.push(arrowOf(moment.played_uci, "played"));
    draw();

    const verdict = !outcome
      ? h("p", {}, "The move was ", h("strong", { class: "cls-best" }, moment.answer_san), ".")
      : outcome.alternative
        ? h("p", { class: "moment-verdict" }, h("strong", { class: "cls-good" }, `${outcome.san} is good too.`), " The engine's choice was ", h("strong", {}, moment.answer_san), ".")
        : h("p", { class: "moment-verdict" }, h("strong", { class: "cls-best" }, `Correct: ${outcome.san}.`));
    const played =
      moment.played_uci !== moment.answer_uci
        ? h("p", { class: "muted small" }, `In the game: ${moveLabel(moment, moment.played_san)} (red arrow). The green arrow is the engine's move.`)
        : null;
    // Great and brilliant moments: the summary already is the first reason.
    const reasons = moment.explanation.filter((reason) => reason.text !== moment.text);
    const kind = HIGHLIGHTS.includes(moment.kind) ? moment.kind : moment.kind === "punished" ? "best" : badgeKind(moment);
    clear(element);
    append(
      element,
      header(moment),
      verdict,
      h("div", { class: "moment-summary" }, h("strong", { class: `cls-${kind}` }, moment.title), h("p", {}, moment.text)),
      reasonList(reasons, kind),
      played,
      controls(moment, true),
    );
  }

  function finish() {
    stop();
    element.prepend(notice(`Review done: you found ${found.size} of ${moments.length}.`));
  }

  async function tryMove(from, to) {
    const moment = moments[at];
    const promotes = chess.get(from)?.type === "p" && (to[1] === "8" || to[1] === "1");
    const uci = from + to + (promotes ? "q" : "");
    const san = chess.move({ from, to, promotion: promotes ? "q" : undefined }).san;
    [selected, targets, lastMove] = [null, [], [from, to]];
    draw();
    if (uci === moment.answer_uci) return reveal(moment, { san });

    const mine = ++run;
    phase = "checking";
    let wrongText;
    if (uci === moment.played_uci && ["mistake", "missed"].includes(moment.kind)) {
      wrongText = `${san} is what you played in the game. Try something else.`;
    } else {
      ask(moment, h("p", { class: "muted" }, `Checking ${san}…`));
      let score;
      try {
        score = await api.scoreMove(moment.fen, uci);
      } catch (error) {
        if (mine !== run) return;
        return retry(moment, notice(error.message || "The engine couldn't be reached.", "error"));
      }
      if (mine !== run) return;
      if (score.classification === "good") return reveal(moment, { san, alternative: true });
      wrongText = `${san} gives away about ${Math.round(score.win_pct_loss)}% of your winning chances. Try again.`;
    }
    retry(moment, h("p", { class: "moment-wrong" }, wrongText));
  }

  /** Show why the move failed, then put the position back. */
  function retry(moment, message) {
    ask(moment, message);
    const mine = run;
    timer = setTimeout(() => {
      if (mine !== run) return;
      chess = new Chess(moment.fen);
      [lastMove, phase] = [squaresOf(moment.previous_uci), "asking"];
      draw();
    }, RESET_DELAY_MS);
  }

  function onSquare(square) {
    if (at < 0 || phase !== "asking") return;
    if (selected && targets.includes(square)) {
      tryMove(selected, square);
      return;
    }
    const piece = chess.get(square);
    if (piece && piece.color === chess.turn()) {
      selected = square;
      targets = chess.moves({ square, verbose: true }).map((move) => move.to);
    } else {
      [selected, targets] = [null, []];
    }
    draw();
  }

  /** Give the board back. `silent` skips the page's redraw (it is about to draw anyway). */
  function stop(silent = false) {
    if (at < 0) return;
    run += 1;
    clearTimeout(timer);
    at = -1;
    board.setInteractive(borrowed.interactive, borrowed.onSquare);
    board.setArrows([]);
    onActive(false);
    overview();
    if (!silent) onReview(undefined);
  }

  overview();
  return { element, start, stop, active: () => at >= 0 };
}
