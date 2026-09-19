/**
 * Client-side session log using localStorage. Every rep is stored under
 * `physiolive.sessions[userId]` as a JSON array. The dashboard tabs
 * read from here for the Session and Progress views.
 */

const KEY = "physiolive.sessions";

function load() {
  try {
    return JSON.parse(localStorage.getItem(KEY) || "{}");
  } catch (_) {
    return {};
  }
}

function save(data) {
  try {
    localStorage.setItem(KEY, JSON.stringify(data));
  } catch (_) { /* quota / private mode */ }
}

export function openSession(userId, exercise) {
  const id = "s_" + Date.now().toString(36);
  const all = load();
  const bucket = all[userId] || [];
  bucket.unshift({
    id, exercise, startedAt: Date.now(),
    endedAt: null, reps: [],
  });
  all[userId] = bucket.slice(0, 200);
  save(all);
  return id;
}

export function appendRep(userId, sessionId, rep) {
  const all = load();
  const bucket = all[userId] || [];
  const session = bucket.find((s) => s.id === sessionId);
  if (!session) return;
  session.reps.push(rep);
  save(all);
}

export function closeSession(userId, sessionId) {
  const all = load();
  const bucket = all[userId] || [];
  const session = bucket.find((s) => s.id === sessionId);
  if (session) {
    session.endedAt = Date.now();
    save(all);
  }
}

export function pastSessions(userId, limit = 30) {
  const all = load();
  const bucket = all[userId] || [];
  return bucket.filter((s) => s.endedAt).slice(0, limit);
}

export function currentSession(userId, sessionId) {
  const all = load();
  const bucket = all[userId] || [];
  return bucket.find((s) => s.id === sessionId) || null;
}
