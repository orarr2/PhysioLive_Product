# PhysioLive Web

A browser build of PhysioLive. Runs entirely client-side: the camera
feed and the pose estimation stay on the user's device, and the app
only reaches out to the PhysioLive VM when it needs a citation-grounded
coach message.

## Local preview

```
python -m http.server 8080 --directory webapp
```

Open `http://localhost:8080` in Chrome or Safari. Allow camera access
when prompted. To test camera access from a phone on the same network,
use `python -m http.server 8080 --directory webapp --bind 0.0.0.0` and
open `http://<your-laptop-ip>:8080`.

> Modern browsers require a secure origin (`https://` or `localhost`)
> for `getUserMedia`. On GitHub Pages this is automatic. When testing
> from a phone via LAN, add a self-signed HTTPS proxy such as
> [`mkcert`](https://github.com/FiloSottile/mkcert) + `caddy`.

## Deploying to GitHub Pages

1. Push to `main` on `github.com/orarr2/PhysioLive_Product`.
2. In the repo settings under **Pages**, set the source to
   `Branch: main` / `Folder: /webapp`.
3. Wait one minute; the app publishes at
   `https://orarr2.github.io/PhysioLive_Product/`.

## Configuration

Edit `assets/config.js` after the VM comes online:

```js
export const CONFIG = {
  vmOrigin: "https://physiolive.example.com",
  googleClientId: "1234567890-abc.apps.googleusercontent.com",
};
```

- `vmOrigin`: the origin of the PhysioLive coach + RAG service. When
  left `null`, the web app falls back to rule-only feedback.
- `googleClientId`: OAuth client id for Sign in with Google. Create one
  under [Google Cloud Console](https://console.cloud.google.com/apis/credentials).

## Layout

```
webapp/
  index.html           entry point
  README.md            this file
  assets/
    app.js             wiring
    pose.js            MediaPipe Tasks Vision (PoseLandmarker)
    angles.js          joint-angle math
    rep_counter.js     state machine + confirmation
    rules.js           form-check rules (mirror of Python)
    exercises.js       per-exercise config (mirror of Python JSONs)
    coach_client.js    HTTPS client for the VM coach endpoint
    session.js         client-side session log (localStorage)
    auth.js            Google Identity Services + anon UUID
    config.js          runtime configuration
    style.css          UI styling
```

## What it does not do yet

- **Cross-device history sync**: the client writes to localStorage and
  keeps every session per user id. Sync to the VM happens when the VM
  is online and the user is signed in.
- **PDF export**: the desktop notebook exports a one-page PDF per
  session; the web app currently does not.
- **Push notifications for missed sessions**: planned once the VM is
  online.

## License

MIT.
