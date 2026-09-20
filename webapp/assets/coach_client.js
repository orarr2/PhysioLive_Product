/**
 * Thin client for the coach endpoint on the PhysioLive VM. When the
 * endpoint is unreachable or unset the client resolves with the plain
 * rule verdict so the UI keeps moving forward.
 *
 * Configure the VM origin in `assets/config.js`, or let the app
 * override it at boot from `webapp/tunnel-url.json` (published by the
 * VM every time the tunnel restarts).
 *
 * Retrieval + LLM composition on the VM takes 6 to 12 seconds under
 * normal load. The abort timeout is therefore generous (18s) with a
 * short client-side throttle so the UI does not spam the endpoint.
 */

import { CONFIG, getResolvedVmOrigin } from "./config.js";
import { authHeader } from "./auth.js";

let _lastCall = 0;
const MIN_GAP_MS = 2500;
const REQUEST_TIMEOUT_MS = 18000;

export async function requestCoach({
  exercise, verdictLevel, verdictText, metrics, userId,
  onPending,
}) {
  const now = Date.now();
  if (now - _lastCall < MIN_GAP_MS) return null;
  _lastCall = now;

  const origin = getResolvedVmOrigin();
  if (!origin) return null;

  try { if (onPending) onPending(); } catch (_) { /* ignore */ }

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  try {
    const headers = {
      "Content-Type": "application/json",
      "X-User-Id": userId || "",
      ...authHeader(),
    };
    const res = await fetch(`${origin}/coach/feedback`, {
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
    if (res.status === 401 || res.status === 403) {
      return { text: null, sourceUrl: null, authError: true };
    }
    if (res.status === 429) {
      return { text: null, sourceUrl: null, rateLimited: true };
    }
    if (!res.ok) return null;
    const data = await res.json();
    return {
      text: data.message || verdictText,
      sourceUrl: data.source_url || null,
      sources: data.sources || [],
      usedLlm: !!data.used_llm,
      tookMs: data.took_ms || 0,
    };
  } catch (e) {
    clearTimeout(timer);
    if (e.name === "AbortError") {
      console.warn("coach request aborted after", REQUEST_TIMEOUT_MS, "ms");
    } else {
      console.warn("coach unreachable", e);
    }
    return null;
  }
}
