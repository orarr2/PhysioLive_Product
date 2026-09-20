# Cloudflare Tunnel setup

Expose the PhysioLive service (bound to `127.0.0.1:8000`) over HTTPS
via Cloudflare Tunnel. The tunnel is **outbound-only**: no firewall
ports need to be opened, and Cloudflare handles TLS termination
automatically.

## 1. Install cloudflared on the VM

```
curl -L --output cloudflared.deb \
    https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb
sudo dpkg -i cloudflared.deb
rm cloudflared.deb
cloudflared --version
```

## 2. Authenticate

```
cloudflared tunnel login
```

The command prints a URL. Open it in a browser on your laptop, sign in
to Cloudflare, and pick the domain you want the tunnel to attach to.
The credentials are stored under `~/.cloudflared/`.

## 3. Create a named tunnel

```
cloudflared tunnel create physiolive
```

This writes `~/.cloudflared/<tunnel-id>.json` (the tunnel credentials)
and prints the tunnel id.

## 4. Route a hostname to the tunnel

```
cloudflared tunnel route dns physiolive physiolive.<yourdomain>.com
```

Replace `<yourdomain>.com` with a Cloudflare-managed domain.

## 5. Config file

Create `~/.cloudflared/config.yml`:

```yaml
tunnel: physiolive
credentials-file: /root/.cloudflared/<tunnel-id>.json

ingress:
  - hostname: physiolive.yourdomain.com
    service: http://127.0.0.1:8000
  - service: http_status:404
```

## 6. Systemd unit

```
sudo cloudflared service install
sudo systemctl enable --now cloudflared
sudo systemctl status cloudflared
```

## 7. Verify

From your laptop:

```
curl https://physiolive.yourdomain.com/health
```

Expected: `{"ok": true, "index_ready": true, "chunks_count": 12, ...}`

## 8. Wire the web app and the notebook

In `webapp/assets/config.js`:

```js
export const CONFIG = {
  vmOrigin: "https://physiolive.yourdomain.com",
  googleClientId: "...",
};
```

In the notebook environment (before starting the kernel):

```
PHYSIOLIVE_VM_URL=https://physiolive.yourdomain.com
PHYSIOLIVE_JWT=<paste the jwt returned by /auth/login>
```

## Alternative: TryCloudflare (throw-away URL)

If you do not yet have a Cloudflare-managed domain, you can spin up a
throw-away URL for testing:

```
cloudflared tunnel --url http://127.0.0.1:8000
```

The command prints a `https://<random>.trycloudflare.com` URL that
lives while the process runs. Good for a quick smoke test, but the URL
changes each time.
