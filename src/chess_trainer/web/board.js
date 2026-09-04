// The chessboard: draws a position, marks, arrows and a move badge, and
// reports which square the user picked (by click, tap or drag).
// It knows nothing about chess rules; legality lives in chess.js.

import { append, h, svg } from "./dom.js";

const FILES = "abcdefgh";
const DRAG_THRESHOLD_PX = 5;

export function parseFen(fen) {
  const pieces = new Map(); // "e4" -> "wP"
  const [placement, turn] = fen.split(" ");
  placement.split("/").forEach((row, rowIndex) => {
    let file = 0;
    for (const char of row) {
      if (/\d/.test(char)) {
        file += Number(char);
      } else {
        const color = char === char.toUpperCase() ? "w" : "b";
        pieces.set(`${FILES[file++]}${8 - rowIndex}`, color + char.toUpperCase());
      }
    }
  });
  return { pieces, turn: turn === "b" ? "black" : "white" };
}

/** Square of the king that is in check, or null. `chess` is a chess.js game. */
export function checkedKingSquare(chess) {
  if (!chess.isCheck()) return null;
  for (const row of chess.board()) {
    for (const piece of row) {
      if (piece && piece.type === "k" && piece.color === chess.turn()) return piece.square;
    }
  }
  return null;
}

export class Board {
  /**
   * @param {object} options
   * @param {"white"|"black"} options.orientation which side sits at the bottom
   * @param {boolean} options.interactive accept clicks and drags
   * @param {(square: string) => void} options.onSquare called with each picked square
   * @param {boolean} options.coords show file/rank labels
   */
  constructor({ orientation = "white", interactive = false, onSquare = null, coords = true } = {}) {
    this.orientation = orientation;
    this.interactive = interactive;
    this.onSquare = onSquare;
    this.coords = coords;
    this.squares = new Map();
    this.marks = {};
    this.arrows = [];
    this.badge = null;
    this.fen = null;
    this.grid = h("div", { class: "board-grid" });
    this.overlay = svg("svg", { class: "board-arrows", viewBox: "0 0 8 8", "aria-hidden": "true" });
    this.element = h(
      "div",
      { class: `board${interactive ? " interactive" : ""}`, role: "img", "aria-label": "Chess board" },
      this.grid,
      this.overlay,
    );
    this.build();
    if (interactive) this.enablePointer();
  }

  build() {
    this.grid.replaceChildren();
    this.squares.clear();
    const white = this.orientation === "white";
    const ranks = white ? [8, 7, 6, 5, 4, 3, 2, 1] : [1, 2, 3, 4, 5, 6, 7, 8];
    const files = white ? [...FILES] : [...FILES].reverse();
    for (const rank of ranks) {
      for (const file of files) {
        const name = `${file}${rank}`;
        const dark = (FILES.indexOf(file) + rank) % 2 === 1;
        const square = h("div", { class: `sq ${dark ? "dark" : "light"}`, dataset: { square: name } });
        if (this.coords && file === files[0]) square.append(h("span", { class: "coord coord-rank" }, rank));
        if (this.coords && rank === ranks[7]) square.append(h("span", { class: "coord coord-file" }, file));
        square.append(h("div", { class: "piece" }));
        this.squares.set(name, square);
        this.grid.append(square);
      }
    }
    if (this.fen) this.setPosition(this.fen);
    this.renderMarks();
    this.renderArrows();
    this.renderBadge();
  }

  flip() {
    this.setOrientation(this.orientation === "white" ? "black" : "white");
  }

  setOrientation(orientation) {
    if (orientation === this.orientation) return;
    this.orientation = orientation;
    this.build();
  }

  setPosition(fen) {
    this.fen = fen;
    const { pieces } = parseFen(fen);
    for (const [name, square] of this.squares) {
      const piece = pieces.get(name);
      const element = square.querySelector(".piece");
      element.className = piece ? `piece ${piece}` : "piece";
      element.style.transform = "";
      square.classList.toggle("occupied", Boolean(piece));
    }
    const { turn } = parseFen(fen);
    this.element.setAttribute("aria-label", `Chess board, ${turn} to move`);
  }

  /** marks: { selected, targets: [], lastMove: [], check, hint, wrong } (all square names) */
  setMarks(marks = {}) {
    this.marks = marks;
    this.renderMarks();
  }

  renderMarks() {
    const { selected, targets = [], lastMove = [], check, hint, wrong } = this.marks;
    for (const [name, square] of this.squares) {
      square.classList.toggle("selected", selected === name);
      square.classList.toggle("target", targets.includes(name));
      square.classList.toggle("last-move", lastMove.includes(name));
      square.classList.toggle("in-check", check === name);
      square.classList.toggle("hint", hint === name);
      square.classList.toggle("wrong", wrong === name);
    }
  }

  /** arrows: [{ from, to, kind }] where kind is "best" | "played" | "hint" */
  setArrows(arrows = []) {
    this.arrows = arrows;
    this.renderArrows();
  }

  center(square) {
    const file = FILES.indexOf(square[0]);
    const rank = Number(square[1]);
    return this.orientation === "white" ? [file + 0.5, 8 - rank + 0.5] : [7 - file + 0.5, rank - 0.5];
  }

  renderArrows() {
    this.overlay.replaceChildren();
    for (const { from, to, kind } of this.arrows) {
      const [x1, y1] = this.center(from);
      const [x2, y2] = this.center(to);
      const length = Math.hypot(x2 - x1, y2 - y1) || 1;
      const [ux, uy] = [(x2 - x1) / length, (y2 - y1) / length];
      const head = 0.34; // arrowhead length, in squares
      const [bx, by] = [x2 - ux * (head + 0.08), y2 - uy * (head + 0.08)];
      const [px, py] = [-uy * 0.2, ux * 0.2];
      this.overlay.append(
        svg(
          "g",
          { class: `arrow arrow-${kind}` },
          svg("line", { x1: x1 + ux * 0.28, y1: y1 + uy * 0.28, x2: bx, y2: by }),
          svg("polygon", {
            points: `${x2 - ux * 0.08},${y2 - uy * 0.08} ${bx + px},${by + py} ${bx - px},${by - py}`,
          }),
        ),
      );
    }
  }

  /** badge: { square, kind, symbol } shown on the corner of a square, or null */
  setBadge(badge = null) {
    this.badge = badge;
    this.renderBadge();
  }

  renderBadge() {
    this.grid.querySelector(".sq-badge")?.remove();
    if (!this.badge) return;
    const square = this.squares.get(this.badge.square);
    if (square) square.append(h("span", { class: `sq-badge cls-${this.badge.kind}` }, this.badge.symbol));
  }

  // --- pointer input -----------------------------------------------------------
  // A press reports its square immediately (so click-click works), and a drag
  // that ends on another square reports that one too. The caller's selection
  // logic therefore handles both styles with no special cases.
  enablePointer() {
    let drag = null;
    const squareAt = (x, y) => document.elementFromPoint(x, y)?.closest?.(".sq")?.dataset.square || null;

    this.grid.addEventListener("pointerdown", (event) => {
      if (event.button !== 0 && event.pointerType === "mouse") return;
      const name = event.target.closest(".sq")?.dataset.square;
      if (!name || !this.onSquare) return;
      event.preventDefault();
      this.onSquare(name);
      // Only start dragging if that press selected a piece.
      if (this.marks.selected !== name) return;
      const piece = this.squares.get(name).querySelector(".piece");
      drag = { from: name, piece, x: event.clientX, y: event.clientY, moved: false };
      this.grid.setPointerCapture(event.pointerId);
    });

    this.grid.addEventListener("pointermove", (event) => {
      if (!drag) return;
      const [dx, dy] = [event.clientX - drag.x, event.clientY - drag.y];
      if (!drag.moved && Math.hypot(dx, dy) < DRAG_THRESHOLD_PX) return;
      drag.moved = true;
      drag.piece.classList.add("dragging");
      drag.piece.style.transform = `translate(${dx}px, ${dy}px) scale(1.08)`;
    });

    const end = (event) => {
      if (!drag) return;
      const { from, piece, moved } = drag;
      drag = null;
      piece.classList.remove("dragging");
      piece.style.transform = "";
      if (!moved || event.type === "pointercancel") return;
      const to = squareAt(event.clientX, event.clientY);
      if (to && to !== from) this.onSquare(to);
    };
    this.grid.addEventListener("pointerup", end);
    this.grid.addEventListener("pointercancel", end);
  }
}

/** A small, static board for thumbnails. */
export function miniBoard(fen, orientation = "white") {
  const board = new Board({ orientation, coords: false });
  board.setPosition(fen);
  board.element.classList.add("mini");
  return board.element;
}

/** Vertical bar showing who is better. set(whiteWinPct, label). */
export function createEvalBar() {
  const fill = h("div", { class: "evalbar-white" });
  const label = h("span", { class: "evalbar-label" });
  const element = append(h("div", { class: "evalbar", role: "img" }), fill, label);
  return {
    element,
    set(whitePct, text, orientation = "white") {
      const pct = Math.max(3, Math.min(97, whitePct));
      element.classList.toggle("flipped", orientation === "black");
      fill.style.height = `${pct}%`;
      label.textContent = text.replace(/^[+-]/, "");
      label.className = `evalbar-label ${whitePct >= 50 ? "for-white" : "for-black"}`;
      element.setAttribute("aria-label", `Evaluation ${text}; White's winning chances ${Math.round(whitePct)}%`);
    },
  };
}
