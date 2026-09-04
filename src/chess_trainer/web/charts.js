// Small charts drawn with SVG and positioned HTML. No charting library.
// Lines are SVG stretched to the container (non-scaling strokes keep them
// crisp); dots are HTML so they stay round at any aspect ratio.

import { append, h, svg } from "./dom.js";

function stretchedSvg(viewBox, ...children) {
  return svg("svg", { class: "chart-svg", viewBox, preserveAspectRatio: "none", "aria-hidden": "true" }, children);
}

/**
 * Winning chances across a game. `points[i]` is White's win % after i plies
 * (so points[0] is the start position). `markers`: [{ index, kind }].
 * Returns { element, setCurrent(index) } where index -1 is the start position.
 */
export function createEvalGraph(points, markers, onSelect) {
  const last = Math.max(points.length - 1, 1);
  const line = points.map((pct, i) => `${i},${100 - pct}`).join(" L");
  const cursor = h("div", { class: "graph-cursor" });
  const dots = markers.map(({ index, kind }) =>
    h("span", {
      class: `graph-dot cls-${kind}`,
      style: `left:${((index + 1) / last) * 100}%;top:${100 - points[index + 1]}%`,
    }),
  );
  const element = h(
    "div",
    {
      class: "eval-graph",
      role: "img",
      "aria-label": "Winning chances over the game. White's advantage is the light area.",
      onclick: (event) => {
        const box = element.getBoundingClientRect();
        const ply = Math.round(((event.clientX - box.left) / box.width) * last);
        onSelect(Math.max(-1, Math.min(points.length - 2, ply - 1)));
      },
    },
    stretchedSvg(
      `0 0 ${last} 100`,
      svg("path", { class: "graph-area", d: `M0,100 L${line} L${last},100 Z` }),
      svg("line", { class: "graph-mid", x1: 0, y1: 50, x2: last, y2: 50 }),
      svg("path", { class: "graph-line", d: `M${line}` }),
    ),
    dots,
    cursor,
  );
  return {
    element,
    setCurrent(index) {
      cursor.style.left = `${((index + 1) / last) * 100}%`;
    },
  };
}

/** Line chart of a 0-100 value over time. items: [{ value, label }] oldest first. */
export function trendChart(items) {
  const values = items.map((item) => item.value);
  const low = Math.max(0, Math.floor((Math.min(...values) - 8) / 10) * 10);
  const span = 100 - low;
  const last = Math.max(items.length - 1, 1);
  const y = (value) => 100 - ((value - low) / span) * 100;
  const path = values.map((value, i) => `${i},${y(value)}`).join(" L");
  return h(
    "div",
    { class: "trend" },
    h("div", { class: "trend-axis" }, h("span", {}, "100%"), h("span", {}, `${low}%`)),
    h(
      "div",
      { class: "trend-plot" },
      stretchedSvg(
        `0 0 ${last} 100`,
        svg("line", { class: "graph-mid", x1: 0, y1: y((100 + low) / 2), x2: last, y2: y((100 + low) / 2) }),
        svg("path", { class: "trend-line", d: `M${path}` }),
      ),
      items.map((item, i) =>
        h("span", {
          class: "trend-dot",
          style: `left:${(i / last) * 100}%;top:${y(item.value)}%`,
          title: `${item.label}: ${item.value}%`,
        }),
      ),
    ),
  );
}

/** One horizontal bar split into labelled segments. segments: [{ label, value, kind }] */
export function stackedBar(segments) {
  const total = segments.reduce((sum, s) => sum + s.value, 0) || 1;
  const share = (value) => `${((100 * value) / total).toFixed(1)}%`;
  return h(
    "div",
    { class: "stacked" },
    h(
      "div",
      { class: "stacked-bar", role: "img", "aria-label": segments.map((s) => `${s.label} ${share(s.value)}`).join(", ") },
      segments.filter((s) => s.value > 0).map((s) => h("span", { class: `cls-bg-${s.kind}`, style: `width:${share(s.value)}` })),
    ),
    h(
      "ul",
      { class: "legend" },
      segments.map((s) =>
        h(
          "li",
          {},
          h("span", { class: `legend-swatch cls-bg-${s.kind}` }),
          h("span", { class: "legend-label" }, s.label),
          h("strong", {}, s.value),
          h("span", { class: "muted" }, share(s.value)),
        ),
      ),
    ),
  );
}

/** A single proportional bar with its value, for table cells. */
export function meter(value, max, text = value) {
  const width = max > 0 ? Math.max(2, (100 * value) / max) : 0;
  return append(
    h("div", { class: "meter" }),
    h("span", { class: "meter-track" }, h("span", { class: "meter-fill", style: `width:${value > 0 ? width : 0}%` })),
    h("span", { class: "meter-value" }, text),
  );
}
