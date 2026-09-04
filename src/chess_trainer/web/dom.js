// DOM helpers and formatters. Everything is built with createElement and
// textContent, so strings from the API can never inject markup.

const SVG_NS = "http://www.w3.org/2000/svg";

function flatten(children) {
  return children.flat(Infinity).filter((c) => c !== null && c !== undefined && c !== false);
}

function applyAttrs(element, attrs, isSvg) {
  for (const [key, value] of Object.entries(attrs || {})) {
    if (value === null || value === undefined || value === false) continue;
    if (key === "class") element.setAttribute("class", value);
    else if (key.startsWith("on")) element.addEventListener(key.slice(2), value);
    else if (key === "dataset") Object.assign(element.dataset, value);
    else if (!isSvg && key in element && typeof value !== "string") element[key] = value;
    else element.setAttribute(key, value === true ? "" : value);
  }
}

/** Create an element: h("a", { class: "x", href: "#" }, "text", child, [more]). */
export function h(tag, attrs = {}, ...children) {
  const element = document.createElement(tag);
  applyAttrs(element, attrs, false);
  append(element, children);
  return element;
}

/** Same as h() for SVG elements. */
export function svg(tag, attrs = {}, ...children) {
  const element = document.createElementNS(SVG_NS, tag);
  applyAttrs(element, attrs, true);
  append(element, children);
  return element;
}

/** Append children, skipping null/false and flattening arrays (unlike the
 *  native append(), which would print "null" and "[object ...]"). */
export function append(parent, ...children) {
  for (const child of flatten(children)) {
    parent.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return parent;
}

export function clear(element) {
  element.replaceChildren();
  return element;
}

export function formatEval(cp, mate) {
  if (mate !== null && mate !== undefined) return `${mate > 0 ? "+" : "-"}M${Math.abs(mate)}`;
  if (cp === null || cp === undefined) return "";
  if (Math.abs(cp) >= 100000) return cp > 0 ? "1-0" : "0-1"; // checkmate on the board
  return `${cp > 0 ? "+" : ""}${(cp / 100).toFixed(1)}`;
}

export function formatClock(seconds) {
  if (seconds === null || seconds === undefined) return "";
  const whole = Math.max(0, Math.round(seconds));
  return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, "0")}`;
}

export function formatDate(iso) {
  return iso ? new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" }) : "";
}

export function titleCase(text) {
  return String(text).replaceAll("_", " ").replace(/^./, (c) => c.toUpperCase());
}

export function plural(count, word) {
  return `${count} ${word}${count === 1 ? "" : "s"}`;
}
