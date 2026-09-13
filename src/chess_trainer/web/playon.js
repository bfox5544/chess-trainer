// "Keep playing": carry on from any position against the engine, with each of
// your moves scored the way game analysis scores them (best, good,
// inaccuracy, mistake, blunder, and why). Used after a puzzle and from a
// repeated mistake; it borrows the page's board and hands it back on exit.

import { api } from "./api.js";
import { checkedKingSquare } from "./board.js";
import { append, clear, h, titleCase } from "./dom.js";
import { MOVE_KINDS, button, kindBadge, moveKind, notice, reasonList } from "./ui.js";
import { Chess } from "./vendor/chess.js";

const REPLY_DELAY_MS = 450;
const ERRORS = ["inaccuracy", "mistake", "blunder"];
const squaresOf = (uci) => [uci.slice(0, 2), uci.slice(2, 4)];

function gameOverText(chess, userColor) {
  if (chess.isCheckmate()) return chess.turn() === userColor[0] ? "Checkmate. The engine won." : "Checkmate. You won.";
  if (chess.isStalemate()) return "Stalemate: a draw.";
  return "Drawn.";
}

/**
 * createPlayOn({ board, exitLabel, onExit }) -> { element, start(fen, userColor), stop(silent), active() }
 * `onExit` runs when play stops (unless `silent`), so the page can redraw its own position.
 */
export function createPlayOn({ board, exitLabel = "Stop playing", onExit = null }) {
  const status = h("div", { class: "coach", "aria-live": "polite" });
  const line = h("div", { class: "line-moves" });
  const controls = h("div", { class: "continuation-controls" });
  const element = h("div", { class: "play-on", hidden: true }, h("p", { class: "result-why" }, "Playing on"), status, line, controls);

  let chess, userColor, startFen, moves, selected, targets, lastMove, badge, busy, borrowed;
  let live = false;
  let run = 0; // invalidates replies that arrive after stop, take back or restart
  let timer = null;

  const draw = (extra = {}) => {
    board.setPosition(chess.fen());
    board.setArrows([]);
    board.setMarks({ selected, targets, lastMove, check: checkedKingSquare(chess), ...extra });
    board.setBadge(badge);
  };

  const renderLine = () => {
    clear(line);
    append(
      line,
      moves.map((move, i) =>
        h(
          "span",
          { class: `move${move.kind && ERRORS.includes(move.kind) ? ` cls-${move.kind}` : ""}${move.by === "engine" ? " muted" : ""}` },
          move.white || i === 0 ? h("span", { class: "move-number" }, `${move.number}${move.white ? "." : "..."}`) : null,
          move.san,
          move.kind && ERRORS.includes(move.kind) ? h("span", { class: "move-mark" }, MOVE_KINDS[move.kind].symbol) : null,
        ),
      ),
    );
  };

  const renderControls = () => {
    clear(controls);
    append(
      controls,
      button("Take back", { icon: "prev", onclick: takeBack, disabled: busy || !moves.some((move) => move.by === "user") }),
      button(exitLabel, { icon: "close", variant: "ghost", onclick: () => stop() }),
    );
  };

  const say = (...nodes) => {
    clear(status);
    append(status, nodes);
  };

  const prompt = () => {
    if (chess.isGameOver()) return h("p", {}, h("strong", {}, gameOverText(chess, userColor)));
    return h("p", { class: "muted" }, `${titleCase(userColor)} to move. Play any move; it is scored like a move in your game analysis.`);
  };

  /** The verdict on the user's last move, as game analysis words it. */
  const verdict = (score) => {
    const kind = moveKind(score);
    const loss = Math.round(score.win_pct_loss);
    return [
      h(
        "div",
        { class: "coach-head" },
        kindBadge(kind),
        h("strong", { class: `cls-${kind}` }, `${score.move_number}${score.color === "white" ? "." : "..."} ${score.san}`),
        h("span", { class: "coach-label" }, MOVE_KINDS[kind].label),
      ),
      ERRORS.includes(kind) ? h("p", {}, `It gave away about ${loss}% of your winning chances.`) : null,
      !score.is_best && score.best_move_san
        ? h("div", { class: "coach-best" }, h("div", {}, ERRORS.includes(kind) ? "Better was " : "The engine preferred ", h("strong", { class: "cls-best" }, score.best_move_san)))
        : null,
      reasonList(score.explanation, kind),
    ];
  };

  const record = (by, san, kind = null) => {
    const white = chess.turn() === "w";
    moves.push({ by, san, kind, number: chess.moveNumber(), white, fenBefore: chess.fen(), lastMoveBefore: lastMove, badgeBefore: badge });
  };

  /** Play the engine's move on the board; `after` are nodes to keep showing above the prompt. */
  const engineMoves = (move, after = []) => {
    record("engine", move.san);
    chess.move({ from: move.uci.slice(0, 2), to: move.uci.slice(2, 4), promotion: move.uci[4] });
    lastMove = squaresOf(move.uci);
    if (badge && badge.square === lastMove[1]) badge = null; // the scored piece was just taken
    busy = false;
    draw();
    renderLine();
    renderControls();
    say(...after, prompt());
  };

  const fail = (error) => {
    busy = false;
    renderControls();
    say(notice(error.message || "The engine couldn't be reached.", "error"), prompt());
  };

  async function tryMove(from, to) {
    const promotes = chess.get(from)?.type === "p" && (to[1] === "8" || to[1] === "1");
    const uci = from + to + (promotes ? "q" : "");
    const fenBefore = chess.fen();
    record("user", "…");
    const entry = moves[moves.length - 1];
    entry.san = chess.move({ from, to, promotion: promotes ? "q" : undefined }).san;
    [selected, targets, lastMove, badge, busy] = [null, [], [from, to], null, true];
    draw();
    renderLine();
    renderControls();
    say(h("p", { class: "muted" }, `Checking ${entry.san}…`));
    const mine = ++run;
    let score;
    try {
      score = await api.scoreMove(fenBefore, uci);
    } catch (error) {
      if (mine !== run) return;
      takeBack();
      fail(error);
      return;
    }
    if (mine !== run) return;
    const kind = moveKind(score);
    entry.kind = kind;
    badge = kind === "good" ? null : { square: to, kind, symbol: MOVE_KINDS[kind].symbol };
    draw();
    renderLine();
    const shown = verdict(score);
    if (!score.reply || chess.isGameOver()) {
      busy = false;
      renderControls();
      say(...shown, prompt());
      return;
    }
    say(...shown);
    timer = setTimeout(() => {
      if (mine === run) engineMoves(score.reply, shown);
    }, REPLY_DELAY_MS);
  }

  function onSquare(square) {
    if (!live || busy || chess.isGameOver() || chess.turn() !== userColor[0]) return;
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

  /** Undo your last move and the engine's answer to it. */
  function takeBack() {
    const index = moves.findLastIndex((move) => move.by === "user");
    if (index < 0) return;
    run += 1;
    clearTimeout(timer);
    const move = moves[index];
    moves = moves.slice(0, index);
    chess = new Chess(move.fenBefore);
    [selected, targets, lastMove, badge, busy] = [null, [], move.lastMoveBefore, move.badgeBefore, false];
    draw();
    renderLine();
    renderControls();
    say(prompt());
  }

  /** Take over the board from `fen`. If it is not the user's turn, the engine moves first. */
  async function start(fen, color) {
    if (live) stop(true);
    borrowed = { interactive: board.interactive, onSquare: board.onSquare };
    board.setInteractive(true, onSquare);
    [chess, userColor, startFen, moves] = [new Chess(fen), color, fen, []];
    [selected, targets, lastMove, badge, busy, live] = [null, [], [], null, false, true];
    element.hidden = false;
    draw();
    renderLine();
    renderControls();
    if (chess.isGameOver() || chess.turn() === userColor[0]) {
      say(prompt());
      return;
    }
    busy = true;
    renderControls();
    say(h("p", { class: "muted" }, "The engine is choosing its move…"));
    const mine = ++run;
    try {
      const { move } = await api.engineReply(startFen);
      if (mine !== run) return;
      if (move) engineMoves(move);
      else fail(new Error("The game is over in this position."));
    } catch (error) {
      if (mine === run) fail(error);
    }
  }

  function stop(silent = false) {
    if (!live) return;
    live = false;
    run += 1;
    clearTimeout(timer);
    board.setInteractive(borrowed.interactive, borrowed.onSquare);
    board.setBadge(null);
    element.hidden = true;
    if (!silent && onExit) onExit();
  }

  return { element, start, stop, active: () => live };
}
