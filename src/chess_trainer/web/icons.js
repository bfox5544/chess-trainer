// A small set of line icons (24x24, stroke = currentColor).

import { svg } from "./dom.js";

const PATHS = {
  home: ["M3 10.5 12 3l9 7.5V20a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z"],
  games: ["M4 4h16v16H4z", "M4 12h16M12 4v16"],
  puzzle: ["M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18z", "M12 16a4 4 0 1 0 0-8 4 4 0 0 0 0 8z", "M12 12h.01"],
  stats: ["M4 20V11M10 20V4M16 20v-7M21 20H3"],
  import: ["M12 3v12m0 0-4-4m4 4 4-4", "M4 19h16"],
  flip: ["M7 4v16m0 0-3-3m3 3 3-3", "M17 20V4m0 0-3 3m3-3 3 3"],
  first: ["M6 5v14", "M19 5l-9 7 9 7z"],
  prev: ["M16 5l-9 7 9 7z"],
  next: ["M8 5l9 7-9 7z"],
  last: ["M18 5v14", "M5 5l9 7-9 7z"],
  check: ["M5 12.5l4.5 4.5L19 7.5"],
  close: ["M6 6l12 12M18 6 6 18"],
  hint: ["M9 18h6M10 21h4", "M12 3a6 6 0 0 0-3.5 10.9c.6.5 1 1.2 1 2.1h5c0-.9.4-1.6 1-2.1A6 6 0 0 0 12 3z"],
  eye: ["M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7-10-7-10-7z", "M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6z"],
  retry: ["M4 12a8 8 0 1 0 2.6-5.9", "M4 4v5h5"],
  user: ["M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8z", "M4 21c0-4 3.6-7 8-7s8 3 8 7"],
  alert: ["M12 4 2.5 20h19z", "M12 10v5M12 17.6v.1"],
  arrow: ["M5 12h14m0 0-6-6m6 6-6 6"],
  clock: ["M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18z", "M12 7v5l3 2"],
  skip: ["M5 5l9 7-9 7z", "M18 5v14"],
  sound: ["M4 9h4l5-4v14l-5-4H4z", "M16.5 8.5a5 5 0 0 1 0 7", "M19 6a8.5 8.5 0 0 1 0 12"],
  muted: ["M4 9h4l5-4v14l-5-4H4z", "M17 9.5l5 5m0-5-5 5"],
};

export function icon(name, size = 20) {
  return svg(
    "svg",
    {
      class: "icon",
      viewBox: "0 0 24 24",
      width: size,
      height: size,
      fill: "none",
      stroke: "currentColor",
      "stroke-width": 1.8,
      "stroke-linecap": "round",
      "stroke-linejoin": "round",
      "aria-hidden": "true",
    },
    PATHS[name].map((d) => svg("path", { d })),
  );
}
