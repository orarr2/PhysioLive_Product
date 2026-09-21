# PhysioLive Web

Browser build of PhysioLive. Runs entirely client-side: the camera feed
and the MediaPipe Pose stay on the user's device, and the app only
reaches out to the PhysioLive VM for citation-grounded coach messages.
Access is JWT-gated - either Google Sign-In or an invite passphrase.

Live: https://orarr2.github.io/PhysioLive_Product/

## Local preview

```
python -m http.server 8080 --directory webapp
```

Open `http://localhost:8080` in Chrome or Safari. Modern browsers
require a secure origin (`https://` or `localhost`) for
`getUserMedia`; on GitHub Pages this is automatic.

To test camera access from a phone on the same LAN, bind to `0.0.0.0`
and add a self-signed HTTPS proxy such as
[`mkcert`](https://github.com/FiloSottile/mkcert) + `caddy`:

```
python -m http.server 8080 --directory webapp --bind 0.0.0.0
```

## Deploying to GitHub Pages

`.github/workflows/pages.yml` runs on every push to `main` that
touches `webapp/`. In the repo settings under **Pages**, set the source
to `GitHub Actions`.

## Configuration

Two files feed the runtime:

```js
// webapp/assets/config.js  (hardcoded fallback, checked into git)
export const CONFIG = {
  vmOrigin: "https://<fallback>.trycloudflare.com",
  googleClientId: null,           // paste your Google OAuth client id
  tunnelJsonTimeoutMs: 1500,
};
```

```json
// webapp/tunnel-url.json  (auto-updated by the VM's publisher unit)
{
  "origin": "https://<current>.trycloudflare.com",
  "published_at": "2026-01-15T09:32:12Z",
  "source": "cloudflared-quick-tunnel"
}
```

The app fetches `tunnel-url.json` at boot and prefers its `origin`;
`CONFIG.vmOrigin` is used only when the JSON is absent or stale. See
`src/vm/deploy/tunnel-publisher.md` for the publisher setup.

## Sign-in gate

The sign-in modal is required - no guest mode. Two paths:

- **Google Sign-In** (visible when `CONFIG.googleClientId` is set):
  the browser gets an ID token, the app posts it to `/auth/google`,
  the VM verifies against Google's tokeninfo endpoint and against the
  `PHYSIOLIVE_ALLOWED_EMAILS` list, and returns a signed JWT.
- **Passphrase** (always visible): the user pastes a shared invite
  passphrase; the VM validates it against `PHYSIOLIVE_PASSPHRASE_HASH`
  and returns the same shape of JWT.

Every subsequent `/rag/query` and `/coach/feedback` call sends the
JWT as a Bearer header. The JWT expires after 7 days by default (see
`PHYSIOLIVE_JWT_TTL`).

## Camera picker

`webapp/assets/app.js` calls `enumerateDevices()` after the first
successful `getUserMedia` grant and populates a dropdown in the top
of the live stage. The choice is stored in `localStorage` under
`physiolive.camera_device_id` and reused on the next session.

The front camera is mirrored automatically via `transform: scaleX(-1)`
on both the video and the overlay canvas, so "move phone right"
matches "the frame moves right". The rear camera stays unmirrored.

## Layout

```
webapp/
  index.html                 entry point
  README.md                  this file
  tunnel-url.json            current tunnel origin (auto-updated)
  assets/
    app.js                   wiring (views, camera, sign-in)
    pose.js                  MediaPipe Tasks Vision (PoseLandmarker)
    angles.js                joint-angle math
    rep_counter.js           state machine + two-tick confirmation
    rules.js                 form-check rules (mirror of Python)
    exercises.js             per-exercise config
    coach_client.js          HTTPS client for /coach/feedback
    session.js               client-side session log (localStorage)
    auth.js                  Google Identity Services + passphrase + JWT
    config.js                runtime configuration + tunnel-url resolver
    style.css                UI styling
```

## What it does not do yet

- **Cross-device history sync.** Sessions live in localStorage. Sync
  to the VM is planned once the auth flow settles in practice.
- **PDF export.** The desktop notebook exports a one-page PDF per
  session; the web app currently does not.
- **Named tunnel.** The tunnel URL is a TryCloudflare hostname that
  changes on every restart. The VM's publisher unit patches the web
  app config automatically so the site follows it, but latency is 60
  to 90 seconds on each cutover. Move to a named tunnel with a stable
  hostname if that gap becomes a problem.

## License

MIT.
