// The puzzle trainer: board, move checking, hints, solution playback. Shared by
// puzzles from your own games and puzzles from the Lichess database; each page
// supplies a `spec` describing the puzzle and what to show around it.
//
// spec = {
//   historyKey, userId,
//   fen,                      // position the puzzle starts from
//   setup: {uci} | null,      // opponent move played before the solver's turn
//   userColor, solution: [{uci, san, by: "user"|"opponent"}],
//   title, subtitle, back: {href, label}, prevHref, nextHref | onNext(),
//   firstTryText,             // shown when solved cleanly
//   wrongMoveText(uci, step), // optional: {title, text} for a specific wrong move
//   result(),                 // node shown once finished
//   facts(finished),          // [[label, value], ...] for the "About" panel
//   finishedLinks(),          // extra buttons once finished
//   onAttempt({solved, firstTry}), // optional: called once per run when it ends
//                             // (finished, or abandoned after a wrong move or
//                             // hint); may return a node (or a promise of one)
//                             // to show under the result
// }

import { Board, checkedKingSquare } from "./board.js";
import { append, clear, formatDate, h, plural, titleCase } from "./dom.js";
import { loadHistory, recordAttempt } from "./history.js";
import { icon } from "./icons.js";
import { button, notice, panel } from "./ui.js";
import { Chess } from "./vendor/chess.js";

const REPLY_DELAY_MS = 450;
const SETUP_DELAY_MS = 600;
const squaresOf = (uci) => [uci.slice(0, 2), uci.slice(2, 4)];

export function historyText(entry) {
  if (!entry) return "First attempt";
  const state = entry.solved ? (entry.firstTry ? "Solved first try" : "Solved") : "Not solved yet";
  return `${state} · ${plural(entry.attempts, "attempt")}, last ${formatDate(entry.lastAt)}`;
}

export function mountTrainer(container, spec) {
  const userSteps = spec.solution.filter((step) => step.by === "user").length;

  const feedback = h("div", { class: "feedback", "aria-live": "polite" });
  const pips = h("div", { class: "pips", "aria-hidden": "true" });
  const lineBox = h("div", { class: "solution-line" });
  const actions = h("div", { class: "puzzle-actions" });
  const result = h("div");
  const factsBox = h("div");
  const board = new Board({ orientation: spec.userColor, interactive: true, onSquare: (square) => onSquare(square) });

  let chess, step, selected, targets, wrongTries, hints, finished, revealed, timers, lastMove, waiting;
  let run = 0; // counts restarts, so a late onAttempt result is not shown on a new run
  let reported = true; // whether this run's outcome has been passed to onAttempt

  /** Tell the page how this run ended, once. */
  const report = (outcome) => {
    if (reported || !spec.onAttempt) return null;
    reported = true;
    return spec.onAttempt(outcome);
  };
  /** A run left after a wrong move or a hint counts as a failed attempt. */
  const abandon = () => {
    if (wrongTries || hints || revealed) report({ solved: false, firstTry: false });
  };

  const draw = (extra = {}) => {
    board.setPosition(chess.fen());
    board.setMarks({ selected, targets, lastMove, check: checkedKingSquare(chess), ...extra });
  };

  const say = (kind, title, text) => {
    const iconName = { success: "check", error: "close", info: null }[kind];
    clear(feedback).append(
      h(
        "div",
        { class: `feedback-box feedback-${kind}` },
        iconName ? h("span", { class: "feedback-icon" }, icon(iconName, 18)) : h("span", { class: `color-dot ${spec.userColor} large` }),
        h("div", {}, h("strong", {}, title), text ? h("p", {}, text) : null),
      ),
    );
  };

  const renderProgress = () => {
    const found = spec.solution.slice(0, step).filter((s) => s.by === "user").length;
    clear(pips);
    append(pips, Array.from({ length: userSteps }, (_, i) => h("span", { class: `pip${i < found ? " done" : ""}` })));
    clear(lineBox);
    if (step) append(lineBox, spec.solution.slice(0, step).map((s) => h("span", { class: `line-move ${s.by}` }, s.san)));
  };

  const renderFacts = () => {
    const rows = [...spec.facts(finished), ["Your history", historyText(loadHistory(spec.userId)[spec.historyKey])]];
    clear(factsBox).append(
      panel("About this puzzle", h("dl", { class: "facts" }, rows.map(([label, value]) => [h("dt", {}, label), h("dd", {}, value)]))),
    );
  };

  const goNext = async () => {
    if (spec.nextHref) {
      location.hash = spec.nextHref;
      return;
    }
    try {
      await spec.onNext();
    } catch (error) {
      clear(result).append(notice(error.message || "Couldn't load the next puzzle.", "error"));
    }
  };
  const hasNext = Boolean(spec.nextHref || spec.onNext);

  const renderActions = () => {
    clear(actions);
    if (finished) {
      append(
        actions,
        hasNext ? button("Next puzzle", { variant: "primary", icon: "next", onclick: goNext }) : null,
        button("Try again", { icon: "retry", onclick: reset }),
        spec.finishedLinks ? spec.finishedLinks() : null,
      );
      return;
    }
    append(
      actions,
      button(hints ? "Show the move" : "Hint", { icon: "hint", onclick: hint, disabled: revealed || waiting }),
      button("Show solution", { icon: "eye", onclick: showSolution, disabled: revealed || waiting }),
      button("Restart", { icon: "retry", variant: "ghost", onclick: reset }),
    );
  };

  const yourTurn = () => {
    waiting = false;
    renderActions();
    say("info", `${titleCase(spec.userColor)} to move`, userSteps > 1 ? `Find the best move. ${userSteps} moves to find in total.` : "Find the best move.");
  };

  function reset() {
    if (run) abandon();
    run += 1;
    reported = false;
    (timers || []).forEach(clearTimeout);
    timers = [];
    chess = new Chess(spec.fen);
    [step, wrongTries, hints, finished, revealed] = [0, 0, 0, false, false];
    [selected, targets, lastMove] = [null, [], []];
    waiting = Boolean(spec.setup);
    board.setArrows([]);
    clear(result);
    renderProgress();
    renderActions();
    renderFacts();
    draw();
    if (!spec.setup) return yourTurn();
    // Lichess puzzles start one move early: show the opponent's move first.
    say("info", "Watch your opponent's move", null);
    timers.push(
      setTimeout(() => {
        const uci = spec.setup.uci;
        chess.move({ from: uci.slice(0, 2), to: uci.slice(2, 4), promotion: uci[4] });
        lastMove = squaresOf(uci);
        draw();
        yourTurn();
      }, SETUP_DELAY_MS),
    );
  }

  const play = (uci) => {
    chess.move({ from: uci.slice(0, 2), to: uci.slice(2, 4), promotion: uci[4] });
    step += 1;
    [selected, targets, lastMove] = [null, [], squaresOf(uci)];
    board.setArrows([]);
    renderProgress();
    draw();
  };

  const finish = (kind, title, text) => {
    finished = true;
    const clean = !revealed && wrongTries === 0 && hints === 0;
    recordAttempt(spec.userId, spec.historyKey, { solved: !revealed, firstTry: clean });
    say(kind, title, text);
    clear(result).append(spec.result());
    const thisRun = run;
    Promise.resolve(report({ solved: !revealed, firstTry: clean }))
      .then((node) => {
        if (node && thisRun === run) append(result, node);
      })
      .catch(() => {});
    renderActions();
    renderFacts();
  };

  const afterUserMove = () => {
    if (step >= spec.solution.length) {
      if (revealed) finish("info", "Solution shown", "Play it through again to make it stick.");
      else if (wrongTries || hints) finish("success", "Solved", `${wrongTries ? plural(wrongTries, "wrong try") : "No wrong tries"}${hints ? ", with a hint" : ""}.`);
      else finish("success", "Solved on the first try", spec.firstTryText);
      return;
    }
    if (!revealed) say("success", "Correct", "Keep going. What's next?");
    timers.push(
      setTimeout(() => {
        play(spec.solution[step].uci); // the opponent's reply
        if (revealed) revealNext();
      }, REPLY_DELAY_MS),
    );
  };

  const revealNext = () => {
    timers.push(
      setTimeout(() => {
        play(spec.solution[step].uci);
        afterUserMove();
      }, REPLY_DELAY_MS),
    );
  };

  const tryMove = (from, to) => {
    const expected = spec.solution[step].uci;
    const promotes = chess.get(from)?.type === "p" && (to[1] === "8" || to[1] === "1");
    // Promote to what the solution wants when the squares match, else a queen.
    const promotion = promotes ? (expected.slice(0, 4) === from + to ? expected[4] : "q") : "";
    const uci = from + to + promotion;
    if (uci === expected) {
      play(uci);
      afterUserMove();
      return;
    }
    // A different move that delivers checkmate is just as good.
    const trial = new Chess(chess.fen());
    trial.move({ from, to, promotion: promotion || undefined });
    if (trial.isCheckmate()) {
      chess = trial;
      [selected, targets, lastMove] = [null, [], [from, to]];
      draw();
      finish("success", "Checkmate", "Not the expected line, but mate is mate.");
      return;
    }
    wrongTries += 1;
    [selected, targets] = [null, []];
    draw({ wrong: to });
    const special = spec.wrongMoveText?.(uci, step);
    say("error", special?.title || "Not the best move", special?.text || "The position is unchanged. Try another move.");
  };

  function onSquare(square) {
    if (finished || revealed || waiting || spec.solution[step]?.by !== "user") return;
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
    board.setArrows([]);
    draw();
  }

  function hint() {
    if (finished || revealed || waiting) return;
    hints += 1;
    const [from, to] = squaresOf(spec.solution[step].uci);
    [selected, targets] = [null, []];
    if (hints === 1) {
      draw({ hint: from });
      say("info", "Hint", "The highlighted piece is the one to move.");
    } else {
      board.setArrows([{ from, to, kind: "hint" }]);
      draw({ hint: from });
      say("info", "Hint", "Play the move shown by the arrow.");
    }
    renderActions();
  }

  function showSolution() {
    if (finished || revealed || waiting) return;
    revealed = true;
    [selected, targets] = [null, []];
    say("info", "Showing the solution…", null);
    renderActions();
    revealNext();
  }

  const onKey = (event) => {
    if (event.target.matches("input, select, textarea, button, a")) return;
    if (finished && hasNext && (event.key === "Enter" || event.key === "n")) goNext();
  };
  document.addEventListener("keydown", onKey);

  append(
    container,
    h("a", { class: "back", href: spec.back.href }, spec.back.label),
    h(
      "div",
      { class: "trainer" },
      h("div", { class: "trainer-board" }, board.element),
      h(
        "div",
        { class: "trainer-side" },
        h(
          "div",
          { class: "trainer-head" },
          h("div", {}, h("h1", {}, spec.title), h("p", { class: "muted small" }, spec.subtitle)),
          h(
            "div",
            { class: "trainer-nav" },
            spec.prevHref ? button("", { icon: "prev", variant: "ghost", href: spec.prevHref, "aria-label": "Previous puzzle" }) : null,
            hasNext ? button("", { icon: "next", variant: "ghost", onclick: goNext, "aria-label": "Next puzzle" }) : null,
          ),
        ),
        feedback,
        h("div", { class: "progress-line" }, pips, lineBox),
        actions,
        result,
        factsBox,
      ),
    ),
  );
  reset();
  return () => {
    abandon();
    timers.forEach(clearTimeout);
    document.removeEventListener("keydown", onKey);
  };
}
