/**
 * Thin client for the daily summary endpoint on the PhysioLive VM.
 * Aggregates every session that started today from the local session
 * log and POSTs them together. The VM composes and emails the report;
 * this client only cares about success or a specific failure.
 */

import { CONFIG, getResolvedVmOrigin } from "./config.js";
import { authHeader } from "./auth.js";
import { EXERCISES } from "./exercises.js";

function _todaysSessions(sessions) {
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const cutoff = today.getTime();
  return (sessions || []).filter(s => s.startedAt && s.startedAt >= cutoff);
}

export async function sendDailyReport(userId, allSessions) {
  const origin = getResolvedVmOrigin();
  if (!origin) return { ok: false, reason: "vm-unreachable" };

  const today = _todaysSessions(allSessions);
  if (!today.length) return { ok: false, reason: "no-sessions-today" };

  const payload = {
    sessions: today.map(s => ({
      exercise: s.exercise,
      exercise_name: (EXERCISES[s.exercise] && EXERCISES[s.exercise].name)
                     || s.exercise,
      startedAt: s.startedAt,
      endedAt: s.endedAt,
      reps: (s.reps || []).map(r => ({
        index: r.index,
        level: r.level,
        text: r.text,
        primary_min: r.primary_min,
        knee_min: r.knee_min,
        hip_min: r.hip_min,
        torso_max: r.torso_max,
      })),
    })),
  };

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 25000);
  try {
    const res = await fetch(`${origin}/report/daily/send`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-User-Id": userId || "",
        ...authHeader(),
      },
      body: JSON.stringify(payload),
      signal: controller.signal,
    });
    clearTimeout(timer);
    if (res.status === 401 || res.status === 403) {
      return { ok: false, reason: "auth-expired" };
    }
    if (res.status === 503) {
      const body = await res.json().catch(() => ({}));
      return { ok: false, reason: "email-not-configured",
               detail: body.detail };
    }
    if (res.status === 429) {
      return { ok: false, reason: "rate-limited" };
    }
    if (!res.ok) {
      return { ok: false, reason: "server-error", status: res.status };
    }
    const data = await res.json();
    return { ok: true, ...data };
  } catch (e) {
    clearTimeout(timer);
    if (e.name === "AbortError") {
      return { ok: false, reason: "timeout" };
    }
    return { ok: false, reason: "network-error", detail: String(e) };
  }
}
