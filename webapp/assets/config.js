/**
 * Runtime configuration read by the web app.
 *
 * The origin of the PhysioLive VM comes from one of two places, in
 * order:
 *   1. `webapp/tunnel-url.json`, published by the VM every time the
 *      cloudflared tunnel restarts. This keeps the site pointed at
 *      the live tunnel without a manual redeploy.
 *   2. `CONFIG.vmOrigin` below, a hardcoded default kept as a fallback
 *      when the JSON is missing or stale.
 *
 * When the tunnel moves to a stable named-tunnel hostname, drop the
 * JSON auto-update and set `vmOrigin` here permanently.
 */

export const CONFIG = {
  // Hardcoded fallback origin - used only when tunnel-url.json is
  // absent or its `origin` field is empty.
  vmOrigin: "https://experienced-read-liked-magnitude.trycloudflare.com",

  // Google Sign-In client id. Create one under "OAuth 2.0 Client IDs"
  // at https://console.cloud.google.com/apis/credentials and paste the
  // value here. When null, only the passphrase route is available in
  // the sign-in modal.
  googleClientId: null,

  // Fraction of a second to wait for tunnel-url.json before falling
  // back to the hardcoded vmOrigin. Keep small; the file lives on the
  // same GitHub Pages origin as the web app so it is cache-friendly.
  tunnelJsonTimeoutMs: 1500,
};


let _resolvedOrigin = null;
let _resolvingPromise = null;

/**
 * Resolve the VM origin once per page load. Returns the URL string
 * (never null); callers can rely on it being set immediately after
 * `resolveVmOrigin()` awaits.
 */
export async function resolveVmOrigin() {
  if (_resolvedOrigin) return _resolvedOrigin;
  if (_resolvingPromise) return _resolvingPromise;
  _resolvingPromise = (async () => {
    try {
      const controller = new AbortController();
      const timer = setTimeout(
        () => controller.abort(), CONFIG.tunnelJsonTimeoutMs);
      // Cache-bust so a fresh tunnel URL is picked up even when the
      // browser has an old copy of tunnel-url.json.
      const res = await fetch(`./tunnel-url.json?t=${Date.now()}`,
                              { cache: "no-store", signal: controller.signal });
      clearTimeout(timer);
      if (res.ok) {
        const data = await res.json();
        if (data && typeof data.origin === "string" && data.origin) {
          _resolvedOrigin = data.origin.replace(/\/$/, "");
          return _resolvedOrigin;
        }
      }
    } catch (_) { /* fall through to hardcoded */ }
    _resolvedOrigin = (CONFIG.vmOrigin || "").replace(/\/$/, "");
    return _resolvedOrigin;
  })();
  return _resolvingPromise;
}

/**
 * Synchronous accessor. Returns the resolved origin after
 * `resolveVmOrigin()` has run, or the hardcoded fallback otherwise.
 * Every runtime call site should first `await resolveVmOrigin()` at
 * boot; this getter is for tight loops that cannot await.
 */
export function getResolvedVmOrigin() {
  return _resolvedOrigin || (CONFIG.vmOrigin || "").replace(/\/$/, "");
}
