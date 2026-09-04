// Solve one puzzle. The API supplies the start position and the full solution
// line; moves are checked here, in the browser.

import { api } from "../api.js";
import { Board, checkedKingSquare } from "../board.js";
import { append, clear, formatDate, h, plural, titleCase } from "../dom.js";
import { loadHistory, recordAttempt } from "../history.js";
import { icon } from "../icons.js";
import { button, chip, panel } from "../ui.js";
import { Chess } from "../vendor/chess.js";

const REPLY_DELAY_MS = 450;
const squaresOf = (uci) => [uci.slice(0, 2), uci.slice(2, 4)];

export async function renderPuzzle(container, context, puzzleId) {
  const user = context.user;
  const [puzzle, all] = await Promise.all([api.puzzle(puzzleId), api.puzzles(user.id)]);
  const ids = all.map((p) => p.id);
  const position = ids.indexOf(puzzle.id);
  const nextId = ids.length > 1 ? ids[(position + 1) % ids.length] : null;
  const prevId = ids.length > 1 ? ids[(position - 1 + ids.length) % ids.length] : null;
  const userSteps = puzzle.solution.filter((step) => step.by === "user").length;
  const previous = loadHistory(user.id)[puzzle.id];

  const feedback = h("div", { class: "feedback", "aria-live": "polite" });
  const pips = h("div", { class: "pips", "aria-hidden": "true" });
  const lineBox = h("div", { class: "solution-line" });
  const actions = h("div", { class: "puzzle-actions" });
  const result = h("div");
  const board = new Board({ orientation: puzzle.user_color, interactive: true, onSquare: (square) => onSquare(square) });

  let chess, step, selected, targets, wrongTries, hints, finished, revealed, timers, lastMove;

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
        iconName ? h("span", { class: "feedback-icon" }, icon(iconName, 18)) : h("span", { class: `color-dot ${puzzle.user_color} large` }),
        h("div", {}, h("strong", {}, title), text ? h("p", {}, text) : null),
      ),
    );
  };

  const renderProgress = () => {
    const found = puzzle.solution.slice(0, step).filter((s) => s.by === "user").length;
    clear(pips);
    append(pips, Array.from({ length: userSteps }, (_, i) => h("span", { class: `pip${i < found ? " done" : ""}` })));
    clear(lineBox);
    if (step) {
      append(lineBox, puzzle.solution.slice(0, step).map((s) => h("span", { class: `line-move ${s.by}` }, s.san)));
    }
  };

  const renderActions = () => {
    clear(actions);
    if (finished) {
      append(
        actions,
        nextId ? button("Next puzzle", { variant: "primary", icon: "next", href: `#/puzzles/${nextId}` }) : null,
        button("Try again", { icon: "retry", onclick: reset }),
        button("See it in the game", { icon: "games", href: `#/games/${puzzle.game_id}/${puzzle.ply}` }),
      );
      return;
    }
    append(
      actions,
      button(hints ? "Show the move" : "Hint", { icon: "hint", onclick: hint, disabled: revealed }),
      button("Show solution", { icon: "eye", onclick: showSolution, disabled: revealed }),
      button("Restart", { icon: "retry", variant: "ghost", onclick: reset }),
    );
  };

  function reset() {
    (timers || []).forEach(clearTimeout);
    timers = [];
    chess = new Chess(puzzle.fen);
    [step, wrongTries, hints, finished, revealed] = [0, 0, 0, false, false];
    [selected, targets, lastMove] = [null, [], []];
    board.setArrows([]);
    clear(result);
    renderProgress();
    renderActions();
    draw();
    say("info", `${titleCase(puzzle.user_color)} to move`, userSteps > 1 ? `Find the best move. ${userSteps} moves to find in total.` : "Find the best move.");
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
    recordAttempt(user.id, puzzle.id, { solved: !revealed, firstTry: clean });
    say(kind, title, text);
    clear(result).append(
      h(
        "div",
        { class: "result-card" },
        h(
          "p",
          {},
          "In the game you played ",
          h("strong", { class: `cls-${puzzle.severity}` }, puzzle.played_san),
          `, leaving you a ${Math.round(puzzle.played_win_pct)}% chance to win. `,
          h("strong", { class: "cls-best" }, puzzle.solution[0].san),
          ` keeps it at ${Math.round(puzzle.solution[0].win_pct)}%.`,
        ),
      ),
    );
    renderActions();
  };

  const afterUserMove = () => {
    if (step >= puzzle.solution.length) {
      if (revealed) finish("info", "Solution shown", "Play it through again to make it stick.");
      else if (wrongTries || hints) finish("success", "Solved", `${wrongTries ? `${plural(wrongTries, "wrong try")}` : "No wrong tries"}${hints ? ", with a hint" : ""}.`);
      else finish("success", "Solved on the first try", "That's the move you missed in the game.");
      return;
    }
    if (!revealed) say("success", "Correct", "Keep going. What's next?");
    timers.push(
      setTimeout(() => {
        play(puzzle.solution[step].uci); // the opponent's reply
        if (revealed) revealNext();
      }, REPLY_DELAY_MS),
    );
  };

  const revealNext = () => {
    timers.push(
      setTimeout(() => {
        play(puzzle.solution[step].uci);
        afterUserMove();
      }, REPLY_DELAY_MS),
    );
  };

  const tryMove = (from, to) => {
    const expected = puzzle.solution[step].uci;
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
      finish("success", "Checkmate", "Not the engine's line, but mate is mate.");
      return;
    }
    wrongTries += 1;
    [selected, targets] = [null, []];
    draw({ wrong: to });
    const repeat = step === 0 && uci === puzzle.played_uci;
    say(
      "error",
      repeat ? "That's what you played in the game" : "Not the best move",
      repeat ? "It was the mistake. Look for something stronger." : "The position is unchanged. Try another move.",
    );
  };

  function onSquare(square) {
    if (finished || revealed || puzzle.solution[step]?.by !== "user") return;
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
    if (finished || revealed) return;
    hints += 1;
    const [from, to] = squaresOf(puzzle.solution[step].uci);
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
    if (finished || revealed) return;
    revealed = true;
    [selected, targets] = [null, []];
    say("info", "Showing the solution…", null);
    renderActions();
    revealNext();
  }

  const onKey = (event) => {
    if (event.target.matches("input, select, textarea, button, a")) return;
    if (finished && nextId && (event.key === "Enter" || event.key === "n")) location.hash = `#/puzzles/${nextId}`;
  };
  document.addEventListener("keydown", onKey);

  append(
    container,
    h("a", { class: "back", href: "#/puzzles" }, "← All puzzles"),
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
          h("div", {}, h("h1", {}, `Puzzle ${position + 1} of ${ids.length}`), h("p", { class: "muted small" }, "From one of your own games")),
          h(
            "div",
            { class: "trainer-nav" },
            prevId ? button("", { icon: "prev", variant: "ghost", href: `#/puzzles/${prevId}`, "aria-label": "Previous puzzle" }) : null,
            nextId ? button("", { icon: "next", variant: "ghost", href: `#/puzzles/${nextId}`, "aria-label": "Next puzzle" }) : null,
          ),
        ),
        feedback,
        h("div", { class: "progress-line" }, pips, lineBox),
        actions,
        result,
        panel(
          "About this puzzle",
          h(
            "dl",
            { class: "facts" },
            h("dt", {}, "Came from"),
            h("dd", {}, chip(`Your ${puzzle.severity}`, puzzle.severity)),
            h("dt", {}, "Phase"),
            h("dd", {}, titleCase(puzzle.phase)),
            h("dt", {}, "Length"),
            h("dd", {}, `${plural(userSteps, "move")} to find`),
            puzzle.themes.length ? [h("dt", {}, "Themes"), h("dd", {}, puzzle.themes.map((t) => chip(titleCase(t))))] : null,
            h("dt", {}, "Your history"),
            h(
              "dd",
              {},
              previous
                ? `${previous.solved ? (previous.firstTry ? "Solved first try" : "Solved") : "Not solved yet"} · ${plural(previous.attempts, "attempt")}, last ${formatDate(previous.lastAt)}`
                : "First attempt",
            ),
          ),
        ),
      ),
    ),
  );
  reset();
  return () => {
    timers.forEach(clearTimeout);
    document.removeEventListener("keydown", onKey);
  };
}
