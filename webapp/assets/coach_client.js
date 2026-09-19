/**
 * Thin client for the coach endpoint on the PhysioLive VM. When the
 * endpoint is unreachable or unset the client resolves with the plain
 * rule verdict so the UI keeps moving forward.
 *
 * Configure the VM origin in `assets/config.js`.
 */

import { CONFIG } from "./config.js";

let _lastCall = 0;
const MIN_GAP_MS = 2500;

export async function requestCoach({
  exercise, verdictLevel, verdictText, metrics, userId
}) {
  const now = Date.now();
  if (now - _lastCall < MIN_GAP_MS) return null;
  _lastCall = now;
  if (!CONFIG.vmOrigin) return null;
  try {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 3500);
    const headers = {
      "Content-Type": "application/json",
      "X-User-Id": userId || "",
    };
    if (CONFIG.apiToken) {
      headers["Authorization"] = `Bearer ${CONFIG.apiToken}`;
    }
    const res = await fetch(`${CONFIG.vmOrigin}/coach/feedback`, {
      method: "POST",
      headers,
      body: JSON.stringify({
        exercise,
        verdict_level: verdictLevel,
        verdict_text: verdictText,
        metrics,
      }),
      signal: controller.signal,
    });
    clearTimeout(timer);
    if (!res.ok) return null;
    const data = await res.json();
    return {
      text: data.message || verdictText,
      sourceUrl: data.source_url || null,
    };
  } catch (e) {
    console.warn("coach unreachable", e);
    return null;
  }
}
