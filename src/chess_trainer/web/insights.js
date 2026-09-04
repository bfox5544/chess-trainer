// Turn the weakness report into a few plain-language findings.
// Each needs a minimum sample so three unlucky moves don't become "a weakness".

import { titleCase } from "./dom.js";

const MIN_PHASE_MOVES = 10;
const MIN_OPENING_MOVES = 15;
const MIN_PRESSURE_MOVES = 5;

function worst(buckets, minMoves) {
  const eligible = buckets.filter((b) => b.stats.moves >= minMoves && b.stats.errors_per_100_moves > 0);
  return eligible.sort((a, b) => b.stats.errors_per_100_moves - a.stats.errors_per_100_moves)[0] || null;
}

export function buildInsights(report) {
  const findings = [];
  const overall = report.overall;

  const phase = worst(report.by_phase, MIN_PHASE_MOVES);
  if (phase && phase.stats.errors_per_100_moves > overall.errors_per_100_moves) {
    findings.push({
      kind: "phase",
      title: `The ${phase.key} is where you slip`,
      text: `${phase.stats.errors_per_100_moves} errors per 100 moves there, against ${overall.errors_per_100_moves} overall.`,
      href: `#/puzzles?phase=${phase.key}`,
      action: `Practice ${phase.key} puzzles`,
    });
  }

  const opening = worst(report.by_opening, MIN_OPENING_MOVES);
  if (opening && report.by_opening.length > 1) {
    findings.push({
      kind: "opening",
      title: `Trouble in the ${titleCase(opening.key)}`,
      text: `${opening.stats.accuracy}% accuracy over ${opening.stats.moves} moves, your lowest among openings you play regularly.`,
      href: "#/stats",
      action: "See openings",
    });
  }

  const under = report.by_time_pressure.find((b) => b.key === "under_pressure");
  const calm = report.by_time_pressure.find((b) => b.key === "not_under_pressure");
  if (under && calm && under.stats.moves >= MIN_PRESSURE_MOVES) {
    const worse = under.stats.errors_per_100_moves > calm.stats.errors_per_100_moves * 1.5;
    findings.push({
      kind: "clock",
      title: worse ? "Time pressure costs you" : "You hold up under time pressure",
      text: worse
        ? `${under.stats.errors_per_100_moves} errors per 100 moves when low on time, against ${calm.stats.errors_per_100_moves} otherwise.`
        : `${under.stats.accuracy}% accuracy when low on time, ${calm.stats.accuracy}% otherwise.`,
      href: "#/stats",
      action: "See details",
    });
  }
  return findings;
}
