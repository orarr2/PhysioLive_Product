# Tunnel URL auto-publisher

TryCloudflare quick-tunnel URLs are ephemeral: every time the
`cloudflared` process restarts (VM reboot, network flap, manual
restart) it hands out a fresh `<name>.trycloudflare.com` hostname.
Without automation, the web app on GitHub Pages keeps pointing at the
previous URL and every request errors out.

This directory wires that gap. Whenever cloudflared boots or its URL
file changes, a systemd path unit fires a one-shot script that reads
the current URL and commits it to `webapp/tunnel-url.json` on the
`main` branch of `orarr2/PhysioLive_Product`. GitHub Pages redeploys
the site in about a minute, and the browser fetches
`tunnel-url.json` at page load and prefers its value over the
hardcoded default in `assets/config.js`.

Total downtime after a tunnel restart: roughly 60 to 90 seconds.

## Files

| file | purpose |
|---|---|
| `publish-tunnel-url.sh` | reads current URL, commits it via the GitHub Contents API |
| `publish-tunnel-url.service` | oneshot systemd unit that runs the script |
| `publish-tunnel-url.path` | watches for URL changes, triggers the service |

## One-time setup

1. **Create a fine-grained PAT.**
   Go to https://github.com/settings/personal-access-tokens/new,
   choose the `PhysioLive_Product` repo, and grant only:
   - Repository permissions -> Contents -> Read and write.
   Set expiry to 90 days (GitHub caps fine-grained PATs there).

2. **Save the PAT config on the VM.**
   ```bash
   sudo mkdir -p /etc/physiolive
   sudo tee /etc/physiolive/tunnel-publisher.env >/dev/null <<'EOF'
   GITHUB_TOKEN=github_pat_XXXXXXXXXXXXXXXXXXXX
   GITHUB_REPO=orarr2/PhysioLive_Product
   GITHUB_BRANCH=main
   EOF
   sudo chmod 600 /etc/physiolive/tunnel-publisher.env
   sudo chown root:root /etc/physiolive/tunnel-publisher.env
   ```

3. **Make cloudflared drop its URL to a file.**
   The publish script reads `/var/log/cloudflared-url.txt` first, then
   falls back to scraping the systemd journal. Either works; the file
   is faster and quieter. Edit your cloudflared systemd unit's
   `ExecStart` to include:
   ```
   ExecStartPost=/usr/bin/env bash -c 'sleep 3 && journalctl -u cloudflared -n 40 --no-pager | grep -oE "https://[a-z0-9-]+\.trycloudflare\.com" | tail -1 > /var/log/cloudflared-url.txt'
   ```
   (Or use whatever cloudflared exposes on your version; the fallback
   handles the case where this file never appears.)

4. **Install the publisher units.**
   ```bash
   sudo install -m 755 /opt/physiolive/repo/src/vm/deploy/publish-tunnel-url.sh \
       /opt/physiolive/repo/src/vm/deploy/publish-tunnel-url.sh
   sudo install -m 644 /opt/physiolive/repo/src/vm/deploy/publish-tunnel-url.service \
       /etc/systemd/system/publish-tunnel-url.service
   sudo install -m 644 /opt/physiolive/repo/src/vm/deploy/publish-tunnel-url.path \
       /etc/systemd/system/publish-tunnel-url.path
   sudo systemctl daemon-reload
   sudo systemctl enable --now publish-tunnel-url.path
   ```

5. **Kick it once manually to verify.**
   ```bash
   sudo systemctl start publish-tunnel-url.service
   sudo journalctl -u publish-tunnel-url.service -n 30 --no-pager
   ```
   You should see `publish-tunnel-url: published https://...trycloudflare.com`.
   Confirm the commit landed on
   https://github.com/orarr2/PhysioLive_Product/commits/main .

## Verifying end to end

After the workflow deploys (GitHub Actions -> Deploy PhysioLive web app
to GitHub Pages), fetch `tunnel-url.json` from the site:

```bash
curl -s https://orarr2.github.io/PhysioLive_Product/tunnel-url.json | jq
```

Expected:

```json
{
  "origin": "https://<current>.trycloudflare.com",
  "published_at": "2026-01-15T09:32:12Z",
  "source": "cloudflared-quick-tunnel"
}
```

Load `https://orarr2.github.io/PhysioLive_Product/` in an incognito
tab; DevTools' Network panel should show `tunnel-url.json` fetched
first, then every `/coach/feedback` request going to the fresh
`.trycloudflare.com` URL.

## Rotation

PATs expire after 90 days. Rotate:

```bash
sudo nano /etc/physiolive/tunnel-publisher.env
sudo systemctl restart publish-tunnel-url.path
```

Nothing else needs touching.
