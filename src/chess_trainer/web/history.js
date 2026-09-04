// Puzzle solving history. The backend does not record attempts yet, so this
// lives in the browser (per user). It is a convenience, not a source of truth.

const key = (userId) => `chessTrainer.history.${userId}`;

export function loadHistory(userId) {
  try {
    return JSON.parse(localStorage.getItem(key(userId)) || "{}");
  } catch {
    return {};
  }
}

/** Record one finished attempt. `firstTry` = solved with no wrong move, hint or reveal. */
export function recordAttempt(userId, puzzleId, { solved, firstTry }) {
  const history = loadHistory(userId);
  const entry = history[puzzleId] || { attempts: 0, solved: false, firstTry: false };
  entry.attempts += 1;
  entry.solved = entry.solved || solved;
  entry.firstTry = entry.firstTry || (firstTry && entry.attempts === 1);
  entry.lastAt = new Date().toISOString();
  history[puzzleId] = entry;
  try {
    localStorage.setItem(key(userId), JSON.stringify(history));
  } catch {
    /* storage unavailable: history just won't persist */
  }
  return entry;
}

export function clearHistory(userId) {
  try {
    localStorage.removeItem(key(userId));
  } catch {
    /* ignore */
  }
}

export function isSolved(history, puzzleId) {
  return Boolean(history[puzzleId]?.solved);
}
