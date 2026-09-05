// Thin wrapper around the backend API. Same origin, so paths are absolute.

export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

async function request(method, path, body) {
  let response;
  try {
    response = await fetch(path, {
      method,
      headers: body ? { "content-type": "application/json" } : {},
      body: body ? JSON.stringify(body) : undefined,
    });
  } catch {
    throw new ApiError("Can't reach the Chess Trainer server. Check that it is still running.", 0);
  }
  if (!response.ok) {
    let detail = "";
    try {
      const data = await response.json();
      if (typeof data.detail === "string") detail = data.detail;
      else if (Array.isArray(data.detail)) detail = data.detail.map((d) => d.msg).join("; ");
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(friendly(response.status, detail), response.status);
  }
  return response.json();
}

function friendly(status, detail) {
  if (status === 409) return "That account is already linked to a profile.";
  if (status === 404) return "That item no longer exists.";
  if (status === 422) return detail ? `Please check your input: ${detail}.` : "Please check your input.";
  if (status >= 500) return "The server ran into a problem. Please try again in a moment.";
  return detail || "Something went wrong. Please try again.";
}

function query(params) {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== null && value !== undefined && value !== "") search.set(key, value);
  }
  const text = search.toString();
  return text ? `?${text}` : "";
}

export const api = {
  listUsers: () => request("GET", "/users"),
  createUser: (displayName) => request("POST", "/users", { display_name: displayName }),
  getUser: (userId) => request("GET", `/users/${userId}`),
  linkAccount: (userId, platform, username) =>
    request("POST", `/users/${userId}/accounts`, { platform, username }),
  importGames: (accountId, options) => request("POST", `/accounts/${accountId}/import`, options),
  job: (jobId) => request("GET", `/jobs/${jobId}`),
  userGames: (userId, filters = {}) =>
    request("GET", `/users/${userId}/games${query({ limit: 100, ...filters })}`),
  gameAnalysis: (gameId) => request("GET", `/games/${gameId}/analysis`),
  report: (userId, filters = {}) => request("GET", `/users/${userId}/report${query(filters)}`),
  puzzles: (userId, filters = {}) =>
    request("GET", `/users/${userId}/puzzles${query({ limit: 100, ...filters })}`),
  puzzle: (puzzleId) => request("GET", `/puzzles/${puzzleId}`),
  librarySummary: () => request("GET", "/library"),
  libraryImport: (limit) => request("POST", "/library/import", { limit }),
  librarySample: (filters = {}) => request("GET", `/library/puzzles${query({ limit: 12, ...filters })}`),
  libraryRandom: (filters = {}) => request("GET", `/library/puzzles/random${query(filters)}`),
  libraryPuzzle: (puzzleId) => request("GET", `/library/puzzles/${encodeURIComponent(puzzleId)}`),
};
