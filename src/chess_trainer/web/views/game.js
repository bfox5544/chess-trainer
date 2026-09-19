// One analyzed game: board with eval bar, eval graph, move coach, move list.

import { api } from "../api.js";
import { Board, checkedKingSquare, createEvalBar } from "../board.js";
import { createEvalGraph } from "../charts.js";
import { append, clear, formatClock, formatDate, formatEval, h, titleCase } from "../dom.js";
import { HIGHLIGHTS, MOVE_KINDS, button, chip, emptyState, kindBadge, moveKind, panel, reasonList } from "../ui.js";
import { Chess } from "../vendor/chess.js";

const ERRORS = ["inaccuracy", "mistake", "blunder"];
const squaresOf = (uci) => [uci.slice(0, 2), uci.slice(2, 4)];

function whitePctAfter(move) {
  return move.color === "white" ? move.win_pct_after : 100 - move.win_pct_after;
}

function whitePctBefore(move) {
  return move.color === "white" ? move.win_pct_before : 100 - move.win_pct_before;
}

/** The engine's line from a position, as SAN, for display. */
export function lineToSan(fen, ucis, limit = 6) {
  const chess = new Chess(fen);
  const sans = [];
  for (const uci of ucis.slice(0, limit)) {
    try {
      sans.push(chess.move({ from: uci.slice(0, 2), to: uci.slice(2, 4), promotion: uci[4] }).san);
    } catch {
      break;
    }
  }
  return sans;
}

/** One or two plain sentences on what the move did. */
function explain(move, mine) {
  const who = mine ? "your" : `${titleCase(move.color)}'s`;
  const before = Math.round(move.win_pct_before);
  const after = Math.round(move.win_pct_after);
  const kind = moveKind(move);
  if (move.is_forced) return "The only legal move.";
  // The API's first reason says what earned the mark.
  if (kind === "brilliant") return `A sacrifice that works: ${who} winning chances stay at about ${after}%.`;
  if (kind === "great") return "The engine's first choice, and every other move was clearly worse.";
  if (kind === "book") return "A known opening move.";
  if (kind === "best") return "The engine's first choice.";
  if (kind === "good") return `A sound move. It keeps ${who} winning chances at about ${after}%.`;

  // The concrete reason (hung piece, missed mate, ...) comes from the API and
  // is listed under this sentence.
  const detail = `It cut ${who} winning chances from ${before}% to ${after}%.`;
  const hurried =
    move.time_spent_s !== null && move.time_spent_s < 3 && move.clock_remaining_s !== null
      ? ` Played in ${Math.round(move.time_spent_s)}s with ${formatClock(move.clock_remaining_s)} on the clock.`
      : "";
  return detail + hurried;
}

export async function renderGame(container, context, gameId, startPly) {
  const report = await api.gameAnalysis(gameId);
  const { game, moves } = report;
  const meta = [formatDate(game.played_at), titleCase(game.time_class), game.opening_name, game.eco].filter(Boolean).join(" · ");

  append(
    container,
    h("a", { class: "back", href: "#/games" }, "← All games"),
    h("header", { class: "page-header" }, h("div", {}, h("h1", {}, `${game.white_username} vs ${game.black_username}`), h("p", { class: "muted" }, `${game.result} · ${meta}`))),
  );
  if (!moves.length) {
    append(
      container,
      emptyState({
        iconName: "clock",
        title: "This game hasn't been analyzed yet",
        text: "Start an import and analysis from the Import page; this game is picked up automatically.",
        action: button("Go to import", { variant: "primary", href: "#/import" }),
      }),
    );
    return;
  }

  const mine = context.user.accounts.map((a) => a.username);
  const userColor = mine.includes(game.black_username.toLowerCase())
    ? "black"
    : mine.includes(game.white_username.toLowerCase())
      ? "white"
      : null;

  const board = new Board({ orientation: userColor || "white" });
  const evalBar = createEvalBar();
  const coach = h("div", { class: "coach", "aria-live": "polite" });
  const moveCells = [];
  const players = { white: playerStrip("white", game), black: playerStrip("black", game) };
  const topSlot = h("div");
  const bottomSlot = h("div");
  let current = -1; // -1 = start position; i = position after moves[i]
  let showingBest = false;

  const points = [whitePctBefore(moves[0]), ...moves.map(whitePctAfter)];
  const markers = moves
    .map((move, index) => ({ index, kind: moveKind(move) }))
    .filter((marker) => ["mistake", "blunder", ...HIGHLIGHTS].includes(marker.kind));
  const graph = createEvalGraph(points, markers, (index) => show(index));

  const fenAfter = (index) => {
    if (index < 0) return moves[0].fen_before;
    if (index + 1 < moves.length) return moves[index + 1].fen_before;
    const chess = new Chess(moves[index].fen_before);
    const uci = moves[index].uci;
    chess.move({ from: uci.slice(0, 2), to: uci.slice(2, 4), promotion: uci[4] });
    return chess.fen();
  };

  const placePlayers = () => {
    const bottom = board.orientation;
    const top = bottom === "white" ? "black" : "white";
    clear(topSlot).append(players[top].element);
    clear(bottomSlot).append(players[bottom].element);
  };

  const updateClocks = () => {
    for (const color of ["white", "black"]) {
      const last = moves.slice(0, current + 1).reverse().find((m) => m.color === color);
      players[color].setClock(last ? last.clock_remaining_s : null);
    }
  };

  function draw() {
    const move = moves[current];
    if (showingBest && move) {
      // Rewind to the moment of decision and compare the two moves.
      board.setPosition(move.fen_before);
      board.setMarks({});
      board.setBadge(null);
      board.setArrows([
        { ...arrowOf(move.uci), kind: "played" },
        { ...arrowOf(move.best_move_uci), kind: "best" },
      ]);
    } else {
      const fen = fenAfter(current);
      board.setPosition(fen);
      board.setArrows([]);
      board.setMarks({ lastMove: move ? squaresOf(move.uci) : [], check: checkedKingSquare(new Chess(fen)) });
      const kind = move ? moveKind(move) : null;
      board.setBadge(kind && kind !== "good" ? { square: move.uci.slice(2, 4), kind, symbol: MOVE_KINDS[kind].symbol } : null);
    }
    const whitePct = points[current + 1];
    const label = move ? formatEval(move.eval_after_cp, move.eval_after_mate) : formatEval(moves[0].eval_before_cp, moves[0].eval_before_mate);
    evalBar.set(whitePct, label, board.orientation);
  }

  function show(index) {
    current = Math.max(-1, Math.min(moves.length - 1, index));
    showingBest = false;
    draw();
    updateClocks();
    graph.setCurrent(current);
    moveCells.forEach((cell, i) => cell.classList.toggle("current", i === current));
    // Scroll only the move list (never the page) to keep the current move in view.
    requestAnimationFrame(() => {
      const cell = moveCells[Math.max(current, 0)];
      const list = cell.closest(".move-list");
      const row = cell.parentElement;
      if (list) list.scrollTop = current < 0 ? 0 : row.offsetTop - list.offsetTop - list.clientHeight / 2 + row.offsetHeight;
    });
    renderCoach();
  }

  function renderCoach() {
    clear(coach);
    const move = moves[current];
    if (!move) {
      append(coach, h("p", { class: "muted" }, "Step through the game with the arrow keys, or jump straight to the next mistake."));
      return;
    }
    const kind = moveKind(move);
    const canCompare = ERRORS.includes(kind) && move.best_move_uci && !move.is_best;
    append(
      coach,
      h(
        "div",
        { class: "coach-head" },
        kindBadge(kind),
        h("strong", { class: `cls-${kind}` }, `${move.move_number}${move.color === "white" ? "." : "..."} ${move.san}`),
        h("span", { class: `coach-label cls-${kind}` }, MOVE_KINDS[kind].label),
        h("span", { class: "coach-eval" }, formatEval(move.eval_after_cp, move.eval_after_mate)),
      ),
      h("p", {}, explain(move, move.color === userColor)),
      reasonList(move.explanation, kind),
      canCompare
        ? h(
            "div",
            { class: "coach-best" },
            h("div", {}, "Better was ", h("strong", { class: "cls-best" }, move.best_move_san), bestLineText(move)),
            button(showingBest ? "Back to the game" : "Show on board", {
              icon: showingBest ? "retry" : "eye",
              onclick: () => {
                showingBest = !showingBest;
                draw();
                renderCoach();
              },
            }),
          )
        : null,
      h("div", { class: "coach-meta" }, chip(titleCase(move.phase)), move.clock_remaining_s !== null ? chip(`${formatClock(move.clock_remaining_s)} left`) : null),
    );
  }

  const nextError = (direction) => {
    for (let i = current + direction; i >= 0 && i < moves.length; i += direction) {
      const relevant = userColor ? moves[i].color === userColor : true;
      if (relevant && ["mistake", "blunder"].includes(moves[i].classification)) return show(i);
    }
    return null;
  };

  const onKey = (event) => {
    if (event.target.matches("input, select, textarea") || event.metaKey || event.ctrlKey) return;
    const actions = {
      ArrowLeft: () => show(current - 1),
      ArrowRight: () => show(current + 1),
      Home: () => show(-1),
      End: () => show(moves.length - 1),
      f: flip,
    };
    if (actions[event.key]) {
      event.preventDefault();
      actions[event.key]();
    }
  };
  function flip() {
    board.flip();
    placePlayers();
    draw();
  }
  document.addEventListener("keydown", onKey);

  append(
    container,
    h(
      "div",
      { class: "analysis" },
      h(
        "div",
        { class: "analysis-board" },
        topSlot,
        h("div", { class: "board-row" }, evalBar.element, board.element),
        bottomSlot,
        h(
          "div",
          { class: "controls" },
          button("", { icon: "first", "aria-label": "First move", title: "Start (Home)", onclick: () => show(-1) }),
          button("", { icon: "prev", "aria-label": "Previous move", title: "Previous (←)", onclick: () => show(current - 1) }),
          button("", { icon: "next", "aria-label": "Next move", title: "Next (→)", onclick: () => show(current + 1) }),
          button("", { icon: "last", "aria-label": "Last move", title: "End (End)", onclick: () => show(moves.length - 1) }),
          button("", { icon: "flip", "aria-label": "Flip board", title: "Flip board (F)", onclick: flip }),
          button(userColor ? "Next mistake of mine" : "Next mistake", { icon: "skip", variant: "primary", onclick: () => nextError(1) }),
        ),
      ),
      h(
        "div",
        { class: "analysis-side" },
        h(
          "div",
          { class: "summary" },
          sideSummary(game.white_username, "white", report.white, userColor),
          sideSummary(game.black_username, "black", report.black, userColor),
        ),
        panel(null, coach),
        panel("Winning chances", graph.element, h("p", { class: "muted small" }, "Light area is White's share. Dots mark mistakes, blunders, and great and brilliant moves. Click to jump.")),
        panel("Moves", moveList(moves, moveCells, show)),
      ),
    ),
  );
  placePlayers();
  show(startPly !== undefined && moves[Number(startPly)] ? Number(startPly) : -1);
  return () => document.removeEventListener("keydown", onKey);
}

export function arrowOf(uci) {
  return { from: uci.slice(0, 2), to: uci.slice(2, 4) };
}

function bestLineText(move) {
  const sans = lineToSan(move.fen_before, move.best_line || []);
  return sans.length > 1 ? h("span", { class: "muted" }, ` (line: ${sans.join(" ")})`) : null;
}

function playerStrip(color, game) {
  const name = color === "white" ? game.white_username : game.black_username;
  const rating = color === "white" ? game.white_rating : game.black_rating;
  const clock = h("span", { class: "player-clock" });
  const element = h(
    "div",
    { class: "player" },
    h("span", { class: `color-dot ${color}` }),
    h("strong", {}, name),
    rating ? h("span", { class: "muted" }, rating) : null,
    clock,
  );
  return {
    element,
    setClock(seconds) {
      clock.textContent = formatClock(seconds);
      clock.hidden = seconds === null || seconds === undefined;
    },
  };
}

function sideSummary(name, color, stats, userColor) {
  return h(
    "div",
    { class: `summary-side${color === userColor ? " mine" : ""}` },
    h("div", { class: "summary-name" }, h("span", { class: `color-dot ${color}` }), h("span", {}, name)),
    h("div", { class: "summary-accuracy" }, `${stats.accuracy}%`, h("span", { class: "muted small" }, " accuracy")),
    h(
      "div",
      { class: "summary-counts" },
      ERRORS.map((kind) =>
        h("span", { class: `cls-${kind}`, title: MOVE_KINDS[kind].label }, MOVE_KINDS[kind].symbol, " ", stats[kind === "inaccuracy" ? "inaccuracies" : `${kind}s`]),
      ),
    ),
  );
}

export function moveList(moves, moveCells, show) {
  const rows = [];
  for (let i = 0; i < moves.length; i += 2) {
    rows.push(
      h(
        "div",
        { class: "move-row" },
        h("span", { class: "move-number" }, `${moves[i].move_number}.`),
        moveCell(moves, i, moveCells, show),
        i + 1 < moves.length ? moveCell(moves, i + 1, moveCells, show) : h("span"),
      ),
    );
  }
  return h("div", { class: "move-list" }, rows);
}

function moveCell(moves, index, moveCells, show) {
  const move = moves[index];
  const kind = moveKind(move);
  const flagged = ERRORS.includes(kind) || HIGHLIGHTS.includes(kind);
  const cell = h(
    "button",
    { class: `move${flagged ? ` cls-${kind}` : ""}`, type: "button", onclick: () => show(index) },
    move.san,
    flagged ? h("span", { class: "move-mark", title: MOVE_KINDS[kind].label }, MOVE_KINDS[kind].symbol) : null,
  );
  moveCells[index] = cell;
  return cell;
}
