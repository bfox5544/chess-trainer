// Solve a puzzle made from one of your own mistakes. The trainer itself lives
// in trainer.js; this page supplies the puzzle and the game context.

import { api } from "../api.js";
import { h, plural, titleCase } from "../dom.js";
import { mountTrainer } from "../trainer.js";
import { button, chip, reasonList, themeLabel } from "../ui.js";

export async function renderPuzzle(container, context, puzzleId) {
  const user = context.user;
  const [puzzle, all] = await Promise.all([api.puzzle(puzzleId), api.puzzles(user.id)]);
  const ids = all.map((p) => p.id);
  const position = ids.indexOf(puzzle.id);
  const nextId = ids.length > 1 ? ids[(position + 1) % ids.length] : null;
  const prevId = ids.length > 1 ? ids[(position - 1 + ids.length) % ids.length] : null;
  const userSteps = puzzle.solution.filter((step) => step.by === "user").length;

  return mountTrainer(container, {
    historyKey: puzzle.id,
    userId: user.id,
    fen: puzzle.fen,
    setup: null,
    userColor: puzzle.user_color,
    solution: puzzle.solution,
    title: `Puzzle ${position + 1} of ${ids.length}`,
    subtitle: "From one of your own games",
    back: { href: "#/puzzles", label: "← All puzzles" },
    prevHref: prevId ? `#/puzzles/${prevId}` : null,
    nextHref: nextId ? `#/puzzles/${nextId}` : null,
    firstTryText: "That's the move you missed in the game.",
    wrongMoveText: (uci, step) =>
      step === 0 && uci === puzzle.played_uci
        ? { title: "That's what you played in the game", text: "It was the mistake. Look for something stronger." }
        : null,
    result: () =>
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
        puzzle.explanation?.length ? h("p", { class: "result-why" }, `Why ${puzzle.played_san} was a mistake`) : null,
        reasonList(puzzle.explanation, puzzle.severity),
      ),
    finishedLinks: () => button("See it in the game", { icon: "games", href: `#/games/${puzzle.game_id}/${puzzle.ply}` }),
    facts: () => [
      ["Came from", chip(`Your ${puzzle.severity}`, puzzle.severity)],
      ["Phase", titleCase(puzzle.phase)],
      ["Length", `${plural(userSteps, "move")} to find`],
      ...(puzzle.themes.length ? [["Themes", puzzle.themes.map((t) => chip(themeLabel(t)))]] : []),
    ],
  });
}
