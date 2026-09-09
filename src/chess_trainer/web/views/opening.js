// One opening from the Stats page: its main line on a board, then your games
// in it, one at a time, stopping at each of your errors to show the better move.

import { api } from "../api.js";
import { Board, checkedKingSquare } from "../board.js";
import { append, clear, formatDate, h, plural, titleCase } from "../dom.js";
import { MOVE_KINDS, button, chip, colorDot, emptyState, kindBadge, moveKind, notice, opponentOf, panel, reasonList, resultPill } from "../ui.js";
import { Chess } from "../vendor/chess.js";
import { arrowOf, lineToSan, moveList } from "./game.js";
import { errorCounts } from "./games.js";
import { continuation, repeatedArrows, repeatedCoach, repeatedRow } from "./repeated.js";

const squaresOf = (uci) => [uci.slice(0, 2), uci.slice(2, 4)];
const START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1";

/** "#/stats/opening?family=..." keeping the Stats page filters. */
export function openingHref(family, filters = {}) {
  const params = new URLSearchParams({ family });
  for (const key of ["time_class", "account_id"]) if (filters[key]) params.set(key, filters[key]);
  return `#/stats/opening?${params}`;
}

const moveLabel = (move) => `${move.move_number}${move.color === "white" ? "." : "..."} ${move.san}`;

/** Positions after each move of a UCI line, starting from the initial position. */
function lineFens(steps) {
  const chess = new Chess(START_FEN);
  return steps.map((step) => {
    chess.move({ from: step.uci.slice(0, 2), to: step.uci.slice(2, 4), promotion: step.uci[4] });
    return chess.fen();
  });
}

export async function renderOpening(container, context) {
  const { family, time_class: timeClass = "", account_id: accountId = "" } = context.query;
  if (!family) {
    location.hash = "#/stats";
    return;
  }
  const filters = { family, time_class: timeClass, account_id: accountId };
  let explorer, repeated;
  try {
    [explorer, repeated] = await Promise.all([api.opening(context.user.id, filters), api.repeatedMistakes(context.user.id, filters)]);
  } catch (error) {
    if (error.status !== 404) throw error;
    append(
      container,
      h("a", { class: "back", href: "#/stats" }, "← Stats"),
      emptyState({ iconName: "stats", title: `No analyzed games in the ${family}`, text: "Analyzed games show up here.", action: button("Back to Stats", { href: "#/stats" }) }),
    );
    return;
  }

  const { line, games, stats } = explorer;
  const lineFen = lineFens(line.steps);
  const whiteGames = games.filter((g) => g.user_color === "white").length;
  const board = new Board({ orientation: whiteGames * 2 >= games.length ? "white" : "black" });
  const caption = h("div", { class: "player opening-caption" });
  const coach = h("div", { class: "coach", "aria-live": "polite" });
  const gameMoves = h("div");
  const lineCells = [];
  const gameRows = [];
  const repeatRows = [];
  const controls = h("div", { class: "controls" });

  // mode "line": stepping through the opening line; "game": one of your games;
  // "repeat": a position where you went wrong in several games.
  let mode = "line";
  let repeatIndex = null; // index into repeated
  let repeatLine = null; // its playable best continuation, if any
  let current = line.steps.length - 1;
  let selected = null; // index into games
  let report = null; // that game's full analysis
  let comparing = false; // showing the position before your move, with the better move
  let moveCells = [];
  let loadToken = 0;

  const moves = () => (mode === "game" && report ? report.moves : []);
  const errorPlies = () => new Set(games[selected].errors.map((e) => e.ply));
  const isMyError = (index) => mode === "game" && moves()[index] && errorPlies().has(moves()[index].ply);
  const last = () => (mode === "line" ? line.steps.length - 1 : moves().length - 1);

  const fenAfter = (index) => {
    if (mode === "line") return index < 0 ? START_FEN : lineFen[index];
    const all = moves();
    if (index < 0) return all[0].fen_before;
    if (index + 1 < all.length) return all[index + 1].fen_before;
    const chess = new Chess(all[index].fen_before);
    const uci = all[index].uci;
    chess.move({ from: uci.slice(0, 2), to: uci.slice(2, 4), promotion: uci[4] });
    return chess.fen();
  };

  function draw() {
    if (mode === "repeat") {
      if (repeatLine) return repeatLine.go(repeatLine.at());
      const group = repeated[repeatIndex];
      board.setPosition(group.fen);
      board.setMarks({});
      board.setBadge(null);
      board.setArrows(repeatedArrows(group));
      return;
    }
    const move = mode === "game" ? moves()[current] : null;
    if (comparing && move) {
      board.setPosition(move.fen_before);
      board.setMarks({});
      board.setBadge(null);
      board.setArrows([
        { ...arrowOf(move.uci), kind: "played" },
        { ...arrowOf(move.best_move_uci), kind: "best" },
      ]);
      return;
    }
    const fen = fenAfter(current);
    const uci = mode === "line" ? line.steps[current]?.uci : move?.uci;
    board.setPosition(fen);
    board.setArrows([]);
    board.setMarks({ lastMove: uci ? squaresOf(uci) : [], check: checkedKingSquare(new Chess(fen)) });
    const kind = move ? moveKind(move) : null;
    board.setBadge(kind && kind !== "good" ? { square: move.uci.slice(2, 4), kind, symbol: MOVE_KINDS[kind].symbol } : null);
  }

  function show(index, { compare = false } = {}) {
    if (mode === "repeat") return;
    if (mode === "game" && !report) return;
    current = Math.max(-1, Math.min(last(), index));
    comparing = compare && isMyError(current) && Boolean(moves()[current].best_move_uci);
    draw();
    lineCells.forEach((cell, i) => cell.classList.toggle("current", mode === "line" && i === current));
    moveCells.forEach((cell, i) => cell.classList.toggle("current", i === current));
    const cell = moveCells[Math.max(current, 0)];
    const list = cell?.closest(".move-list");
    if (list) list.scrollTop = current < 0 ? 0 : cell.parentElement.offsetTop - list.offsetTop - list.clientHeight / 2;
    renderCoach();
    renderControls();
  }

  const nextError = (direction = 1) => {
    for (let i = current + direction; i >= 0 && i <= last(); i += direction) {
      if (isMyError(i)) return show(i, { compare: true });
    }
    return null;
  };

  // --- The opening line -------------------------------------------------------

  const lineMoves = h(
    "div",
    { class: "line-moves" },
    line.steps.map((step, i) => {
      const cell = h(
        "button",
        { class: "move", type: "button", onclick: () => showLine(i) },
        i % 2 === 0 ? h("span", { class: "move-number" }, `${i / 2 + 1}.`) : null,
        step.san,
      );
      lineCells.push(cell);
      return cell;
    }),
  );

  function showLine(index = line.steps.length - 1) {
    mode = "line";
    selected = null;
    report = null;
    moveCells = [];
    clear(gameMoves);
    gameRows.forEach((row) => row.classList.remove("selected"));
    repeatRows.forEach((row) => row.classList.remove("selected"));
    clear(caption).append(h("strong", {}, line.name || family));
    setGameInUrl(null);
    show(index);
  }

  // --- Your games -------------------------------------------------------------

  async function openGame(index, ply = null) {
    mode = "game";
    repeatRows.forEach((row) => row.classList.remove("selected"));
    selected = index;
    report = null;
    moveCells = [];
    const entry = games[index];
    const opponent = opponentOf(entry);
    gameRows.forEach((row, i) => row.classList.toggle("selected", i === index));
    clear(caption).append(colorDot(entry.user_color), h("strong", {}, `vs ${opponent.name}`), opponent.rating ? h("span", { class: "muted" }, opponent.rating) : null, resultPill(entry.outcome));
    clear(gameMoves);
    clear(coach).append(h("p", { class: "muted" }, "Loading the game…"));
    setGameInUrl(entry.game.id);
    if (board.orientation !== entry.user_color) board.setOrientation(entry.user_color);
    const token = ++loadToken;
    let loaded;
    try {
      loaded = await api.gameAnalysis(entry.game.id);
    } catch (error) {
      if (token === loadToken) clear(coach).append(notice(error.message || "Couldn't load this game.", "error"));
      return;
    }
    if (token !== loadToken) return;
    report = loaded;
    append(gameMoves, panel("Moves", moveList(report.moves, moveCells, (i) => show(i))));
    const wanted = ply === null ? -1 : report.moves.findIndex((m) => m.ply === ply);
    if (wanted >= 0) return show(wanted, { compare: true });
    // Start at your first error; a clean game starts where it left the book.
    const first = report.moves.findIndex((m) => errorPlies().has(m.ply));
    if (first >= 0) show(first, { compare: true });
    else show(Math.min(report.moves.length - 1, Math.max(entry.game.opening_ply ?? line.steps.length, 1) - 1));
  }

  const gameList = h(
    "ul",
    { class: "game-list" },
    games.map((entry, index) => {
      const opponent = opponentOf(entry);
      const row = h(
        "button",
        { type: "button", class: "game-row", onclick: () => openGame(index) },
        colorDot(entry.user_color),
        h(
          "div",
          { class: "game-row-main" },
          h("div", {}, h("strong", {}, opponent.name), " ", h("span", { class: "muted small" }, formatDate(entry.game.played_at))),
          h("div", { class: "muted small" }, entry.game.opening_name || family),
        ),
        h("div", { class: "game-row-stats" }, resultPill(entry.outcome), entry.stats ? errorCounts(entry.stats) : null),
      );
      gameRows.push(row);
      return h("li", {}, row);
    }),
  );

  // --- Mistakes you repeat in this opening ----------------------------------

  function showRepeat(index) {
    mode = "repeat";
    repeatIndex = (index + repeated.length) % repeated.length;
    selected = null;
    report = null;
    moveCells = [];
    loadToken += 1;
    const group = repeated[repeatIndex];
    clear(gameMoves);
    gameRows.forEach((row) => row.classList.remove("selected"));
    repeatRows.forEach((row, i) => row.classList.toggle("selected", i === repeatIndex));
    lineCells.forEach((cell) => cell.classList.remove("current"));
    setGameInUrl(null);
    if (board.orientation !== group.color) board.setOrientation(group.color);
    clear(caption).append(colorDot(group.color), h("strong", {}, `${titleCase(group.color)} to move`), h("span", { class: "muted" }, `Repeated mistake ${repeatIndex + 1} of ${repeated.length}`));
    repeatLine = continuation(group, board);
    draw();
    const gameLink = (occurrence) => {
      const gameIndex = games.findIndex((g) => g.game.id === occurrence.game_id);
      if (gameIndex < 0) return { href: `#/games/${occurrence.game_id}/${occurrence.ply}` };
      return {
        href: "#",
        onclick: (event) => {
          event.preventDefault();
          openGame(gameIndex, occurrence.ply);
        },
      };
    };
    clear(coach).append(...repeatedCoach(group, { gameLink, line: repeatLine }).filter(Boolean));
    renderControls();
  }

  const repeatList = h(
    "ul",
    { class: "game-list" },
    repeated.map((group, index) => {
      const row = repeatedRow(group, { onclick: () => showRepeat(index) });
      repeatRows.push(row);
      return h("li", {}, row);
    }),
  );

  const setGameInUrl = (gameId) => {
    const params = new URLSearchParams(location.hash.split("?")[1] || "");
    if (gameId) params.set("game", gameId);
    else params.delete("game");
    history.replaceState(null, "", `#/stats/opening?${params}`);
  };

  // --- Coach ------------------------------------------------------------------

  function renderCoach() {
    clear(coach);
    if (mode === "line") {
      const atEnd = current === line.steps.length - 1;
      append(
        coach,
        h("div", { class: "coach-head" }, h("strong", {}, current < 0 ? "Starting position" : atEnd ? line.name || family : `After ${Math.floor(current / 2) + 1}${current % 2 ? "..." : "."} ${line.steps[current].san}`)),
        h(
          "p",
          {},
          line.steps.length
            ? `The way you most often reached the ${family}. Step through it, then go through your games to see where each one went wrong.`
            : "These games have no named opening. Go through them to see where each one went wrong.",
        ),
      );
      return;
    }
    const entry = games[selected];
    const move = moves()[current];
    const errors = entry.errors;
    append(
      coach,
      h(
        "div",
        { class: "coach-head" },
        h("strong", {}, `Game ${selected + 1} of ${games.length}`),
        h("span", { class: "muted small" }, [formatDate(entry.game.played_at), titleCase(entry.game.time_class)].filter(Boolean).join(" · ")),
      ),
    );
    if (!move) {
      append(coach, h("p", { class: "muted" }, "The starting position. Use the arrows, or jump to your next mistake."));
    } else if (isMyError(current) && move.best_move_san) {
      const kind = moveKind(move);
      const bestLine = lineToSan(move.fen_before, move.best_line || []);
      append(
        coach,
        h(
          "div",
          { class: "coach-head" },
          kindBadge(kind),
          h("span", {}, "You played ", h("strong", { class: `cls-${kind}` }, moveLabel(move))),
          h("span", { class: `coach-label cls-${kind}` }, MOVE_KINDS[kind].label),
        ),
        h("p", {}, `It cut your winning chances from ${Math.round(move.win_pct_before)}% to ${Math.round(move.win_pct_after)}%.`),
        reasonList(move.explanation, kind),
        h(
          "div",
          { class: "coach-best" },
          h("div", {}, "You should have played ", h("strong", { class: "cls-best" }, move.best_move_san), bestLine.length > 1 ? h("span", { class: "muted" }, ` (line: ${bestLine.join(" ")})`) : null),
          button(comparing ? "Show the game move" : "Show the better move", {
            icon: comparing ? "next" : "eye",
            onclick: () => show(current, { compare: !comparing }),
          }),
        ),
      );
    } else {
      const kind = moveKind(move);
      const mine = move.color === entry.user_color;
      append(
        coach,
        h(
          "div",
          { class: "coach-head" },
          kindBadge(kind),
          h("strong", { class: `cls-${kind}` }, moveLabel(move)),
          h("span", { class: `coach-label cls-${kind}` }, mine ? MOVE_KINDS[kind].label : `${titleCase(move.color)}'s move`),
        ),
        reasonList(move.explanation, kind),
      );
    }
    append(
      coach,
      errors.length
        ? h(
            "div",
            { class: "error-jumps" },
            h("span", { class: "muted small" }, `Your ${plural(errors.length, "error")}:`),
            errors.map((error) => {
              const index = moves().findIndex((m) => m.ply === error.ply);
              return h(
                "button",
                { type: "button", class: `move cls-${error.classification}${index === current ? " current" : ""}`, onclick: () => show(index, { compare: true }) },
                `${error.move_number}${entry.user_color === "white" ? "." : "..."} ${error.san}`,
                h("span", { class: "move-mark" }, MOVE_KINDS[error.classification].symbol),
              );
            }),
          )
        : h("p", { class: "muted small" }, "No inaccuracies, mistakes or blunders in this game."),
      h(
        "div",
        { class: "coach-meta" },
        button("Previous game", { icon: "prev", variant: "ghost", disabled: selected === 0, onclick: () => openGame(selected - 1) }),
        button("Next game", { icon: "next", variant: "ghost", disabled: selected === games.length - 1, onclick: () => openGame(selected + 1) }),
        button("Full analysis", { icon: "games", variant: "ghost", href: `#/games/${entry.game.id}/${Math.max(current, 0)}` }),
      ),
    );
  }

  function renderControls() {
    if (mode === "repeat") {
      clear(controls).append(
        button("", { icon: "prev", "aria-label": "Previous repeated mistake", title: "Previous mistake (↑)", onclick: () => showRepeat(repeatIndex - 1) }),
        button("", { icon: "next", "aria-label": "Next repeated mistake", title: "Next mistake (↓)", onclick: () => showRepeat(repeatIndex + 1) }),
        button("", { icon: "flip", "aria-label": "Flip board", title: "Flip board (F)", onclick: flip }),
        button("Back to the opening", { icon: "retry", variant: "primary", onclick: () => showLine() }),
      );
      return;
    }
    const hasNextError = mode === "game" && moves().some((_, i) => i > current && isMyError(i));
    clear(controls).append(
      button("", { icon: "first", "aria-label": "Start", title: "Start (Home)", onclick: () => show(-1) }),
      button("", { icon: "prev", "aria-label": "Previous move", title: "Previous (←)", onclick: stepBack }),
      button("", { icon: "next", "aria-label": "Next move", title: "Next (→)", onclick: stepForward }),
      button("", { icon: "last", "aria-label": "Last move", title: "End (End)", onclick: () => show(last()) }),
      button("", { icon: "flip", "aria-label": "Flip board", title: "Flip board (F)", onclick: flip }),
      mode === "line"
        ? button("Go through your games", { icon: "skip", variant: "primary", onclick: () => openGame(0) })
        : hasNextError
          ? button("Next mistake", { icon: "skip", variant: "primary", onclick: () => nextError(1) })
          : selected < games.length - 1
            ? button("Next game", { icon: "skip", variant: "primary", onclick: () => openGame(selected + 1) })
            : button("Back to the opening", { icon: "retry", variant: "primary", onclick: () => showLine() }),
    );
  }

  // From the comparison, "forward" plays the move you actually made.
  // In a repeated mistake, ← → walk its best continuation and ↑ ↓ change mistake.
  const stepForward = () => (mode === "repeat" ? repeatLine?.step(1) : comparing ? show(current) : show(current + 1));
  const stepBack = () => (mode === "repeat" ? repeatLine?.step(-1) : show(current - 1));
  const stepRepeat = (direction) => mode === "repeat" && showRepeat(repeatIndex + direction);
  function flip() {
    board.flip();
    draw();
  }

  const onKey = (event) => {
    if (event.target.matches("input, select, textarea") || event.metaKey || event.ctrlKey) return;
    const actions = {
      ArrowLeft: stepBack,
      ArrowRight: stepForward,
      ...(mode === "repeat" ? { ArrowUp: () => stepRepeat(-1), ArrowDown: () => stepRepeat(1) } : { Home: () => show(-1), End: () => show(last()) }),
      f: flip,
    };
    if (actions[event.key]) {
      event.preventDefault();
      actions[event.key]();
    }
  };
  document.addEventListener("keydown", onKey);

  const filtered = [timeClass && titleCase(timeClass), accountId && "one account"].filter(Boolean);
  append(
    container,
    h("a", { class: "back", href: "#/stats" }, "← Stats"),
    h(
      "header",
      { class: "page-header" },
      h(
        "div",
        {},
        h("h1", {}, family),
        h(
          "p",
          { class: "muted" },
          `${plural(games.length, "analyzed game")} · ${stats.accuracy}% accuracy · ${stats.errors_per_100_moves} errors per 100 moves`,
          filtered.length ? ` · ${filtered.join(", ")}` : "",
        ),
      ),
    ),
    h(
      "div",
      { class: "analysis opening-explorer" },
      h("div", { class: "analysis-board" }, caption, board.element, controls),
      h(
        "div",
        { class: "analysis-side" },
        panel(null, coach),
        panel(
          "The opening",
          line.steps.length ? lineMoves : h("p", { class: "muted" }, "No named opening line."),
          line.steps.length ? button("Show on board", { variant: "ghost", icon: "eye", onclick: () => showLine() }) : null,
        ),
        repeated.length
          ? panel(
              "Mistakes you repeat here",
              h("p", { class: "muted small" }, "Positions in this opening where you went wrong in more than one game."),
              repeatList,
            )
          : null,
        panel(`Your games (${games.length})`, gameList),
        gameMoves,
      ),
    ),
  );

  const startGame = games.findIndex((g) => String(g.game.id) === context.query.game);
  if (startGame >= 0) openGame(startGame);
  else showLine();
  return () => {
    loadToken += 1;
    document.removeEventListener("keydown", onKey);
  };
}
