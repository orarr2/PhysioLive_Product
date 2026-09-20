# Deployment guide

End-to-end setup for the PhysioLive stack. The moving parts are:

- **Web app** on GitHub Pages, served from `webapp/` on `main`.
- **VM** on a Google Cloud e2-micro (Free Tier), running the FastAPI
  service under systemd.
- **Cloudflare Tunnel** exposing the VM over HTTPS with a
  `<name>.trycloudflare.com` hostname.
- **Tunnel URL publisher** on the VM that pushes fresh tunnel URLs to
  `webapp/tunnel-url.json` so the web app follows the tunnel across
  restarts.

## 0. Prerequisites

- A Google account with billing enabled and Free Tier credits.
- A GitHub account (this repo lives under `orarr2/PhysioLive_Product`).
- A Groq API key from https://console.groq.com/keys .
- (Optional) A Google OAuth 2.0 Client ID from
  https://console.cloud.google.com/apis/credentials .

## 1. Web app on GitHub Pages

Already wired. The workflow at `.github/workflows/pages.yml` runs on
every push to `main` that touches `webapp/` or the workflow file
itself, and deploys the folder as a Pages site.

To point the site at a fresh Google Sign-In:

```js
// webapp/assets/config.js
export const CONFIG = {
  vmOrigin: "https://<fallback>.trycloudflare.com",
  googleClientId: "1234567890-abc.apps.googleusercontent.com",  // <- yours
  ...
};
```

Commit the change; the workflow redeploys within a minute.

## 2. Google Cloud VM

Provision an `e2-micro` in `us-west1`, `us-central1`, or `us-east1`
(the three regions that qualify for the Free Tier):

```
gcloud compute instances create physiolive \
  --zone=us-central1-a \
  --machine-type=e2-micro \
  --image-family=debian-13 --image-project=debian-cloud \
  --tags=physiolive \
  --boot-disk-size=30GB --boot-disk-type=pd-standard
```

SSH in and run the installer:

```
gcloud compute ssh physiolive --zone=us-central1-a
sudo bash <(curl -L https://raw.githubusercontent.com/orarr2/PhysioLive_Product/main/src/vm/deploy/setup.sh)
```

The installer creates the `physiolive` system user, clones the repo,
builds a venv, seeds the ChromaDB index from `corpus/`, generates a
JWT signing key at `/var/lib/physiolive/jwt.secret`, and installs the
systemd unit.

Edit `/etc/physiolive/env` and set at minimum:

```
GROQ_API_KEY=gsk_XXXXXXXX
PHYSIOLIVE_PASSPHRASE=some-long-invite-passphrase
```

Optional for the Google Sign-In route:

```
GOOGLE_OAUTH_CLIENT_ID=1234567890-abc.apps.googleusercontent.com
PHYSIOLIVE_ALLOWED_EMAILS=orarbeli1@gmail.com,coach@example.com
```

Start:

```
sudo systemctl start physiolive
curl -s http://127.0.0.1:8000/health | jq
```

Expected:

```json
{
  "ok": true,
  "index_ready": true,
  "chunks_count": 15,
  "coach_provider": "groq",
  "coach_model": "openai/gpt-oss-120b",
  "version": "1.1.0"
}
```

### Bcrypt-hashing the passphrase

The plain form is fine for the first-boot smoke test. Replace with a
bcrypt hash before opening the tunnel:

```
python3 - <<'PY'
import bcrypt, getpass
p = getpass.getpass("passphrase: ").encode()
print(bcrypt.hashpw(p, bcrypt.gensalt()).decode())
PY
```

Paste the resulting `$2b$12$...` into `/etc/physiolive/env` as
`PHYSIOLIVE_PASSPHRASE_HASH=` and comment out the plain form. Restart.

## 3. Cloudflare Tunnel

Follow `src/vm/deploy/cloudflared.md`. TL;DR:

```
sudo apt install cloudflared
sudo cloudflared tunnel --url http://127.0.0.1:8000 --logfile /var/log/cloudflared.log
```

Copy the `.trycloudflare.com` hostname it prints. Verify from your
laptop:

```
curl -s https://<hostname>.trycloudflare.com/health | jq
```

Turn the ad-hoc invocation into a systemd unit so the tunnel comes
back after reboots.

## 4. Tunnel URL auto-publisher

TryCloudflare hostnames change on every restart. `webapp/tunnel-url.json`
is the way the web app follows the tunnel; the publisher on the VM
keeps that file in sync automatically.

Follow `src/vm/deploy/tunnel-publisher.md`:

1. Create a fine-grained GitHub PAT with **Contents: read+write** on
   the `PhysioLive_Product` repo only. 90 days is the max.
2. Save it to `/etc/physiolive/tunnel-publisher.env` (chmod 600).
3. Install the systemd path + service units and enable them.
4. Kick it once manually to verify.

After that, every cloudflared restart triggers a commit that flips
`webapp/tunnel-url.json` on `main`. GitHub Pages redeploys within a
minute and the web app fetches the new URL on the next load.

## 5. Google Sign-In (optional)

1. In https://console.cloud.google.com/apis/credentials, create an
   OAuth 2.0 Client ID of type "Web application".
2. Add these Authorised JavaScript origins:
   - `https://orarr2.github.io`
   - `http://localhost:8080` (local preview)
3. Copy the client id into two places:
   - `webapp/assets/config.js` -> `googleClientId`.
   - `/etc/physiolive/env` -> `GOOGLE_OAUTH_CLIENT_ID`.
4. Fill `PHYSIOLIVE_ALLOWED_EMAILS` in `/etc/physiolive/env` with the
   comma-separated list of emails allowed in.
5. Restart the service.

The web app shows a "Sign in with Google" button when
`googleClientId` is set; the passphrase form stays as a fallback.

## 6. Rate limits, budgets, monitoring

- `docs/rate-limits.md` documents every layer's ceilings and the env
  vars that adjust them.
- The Free Tier e2-micro is 30 GB standard disk + 1 GB RAM. Keep VM
  disk usage under 20 GB (`df -h /`) so log rotation has room; keep
  RAM under 700 MB (`systemctl status physiolive`) so the service
  never triggers systemd's OOM.
- Groq's free tier is generous but not unlimited. See
  https://console.groq.com/settings/limits for your current key's
  numbers and adjust the VM's per-user limit accordingly.

## 7. Testing end to end

```
# 1. Health
curl -s https://<tunnel>.trycloudflare.com/health | jq

# 2. Passphrase login
JWT=$(curl -s -X POST https://<tunnel>.trycloudflare.com/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"passphrase":"<your passphrase>","display_name":"Or"}' | jq -r .jwt)

# 3. Coach with that JWT
curl -s -X POST https://<tunnel>.trycloudflare.com/coach/feedback \
  -H "Authorization: Bearer $JWT" \
  -H 'Content-Type: application/json' \
  -d '{"exercise":"Squat","verdict_level":"warn","verdict_text":"Shallow rep.","metrics":{"knee":110}}' | jq
```

Then open the web app, sign in, do a rep, and check that the coach
banner shows a real LLM sentence with a source link.
