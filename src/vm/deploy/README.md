# PhysioLive VM deployment

Everything under `src/vm/` is the code and configuration that runs on
the PhysioLive Google Cloud VM (an e2-micro in the Free Tier). The VM
hosts the retrieval store and the coach LLM proxy; the pose estimation
and rep counting stay on the user's device.

## Files

- `physiolive.service` - systemd unit that runs `uvicorn` under the
  `physiolive` service user with `MemoryMax=700M` so the free-tier
  VM never gets OOM-killed.
- `setup.sh` - one-shot installer. Installs the apt packages, clones
  the repo, builds the venv, seeds ChromaDB from the corpus seed,
  installs the systemd unit, and configures `ufw`.
- `cloudflared.md` - step-by-step guide for exposing the service over
  HTTPS via Cloudflare Tunnel (outbound-only, no firewall ports).
- `README.md` - this file.

## Quick start

On a fresh Debian 12 or 13 e2-micro VM:

```
curl -L https://raw.githubusercontent.com/orarr2/PhysioLive_Product/main/src/vm/deploy/setup.sh -o setup.sh
sudo bash setup.sh
sudo nano /etc/physiolive/env     # set GROQ_API_KEY + PHYSIOLIVE_API_TOKEN
sudo systemctl start physiolive
curl http://127.0.0.1:8000/health
```

Then follow `cloudflared.md` to attach a public HTTPS hostname.

## Environment variables (`/etc/physiolive/env`)

| var | required | default | notes |
|---|---|---|---|
| `COACH_PROVIDER` | no | `groq` | `groq` or `anthropic` |
| `GROQ_API_KEY` | if provider is `groq` | - | from https://console.groq.com |
| `GROQ_MODEL` | no | `llama-3.3-70b-versatile` | any Groq model id |
| `ANTHROPIC_API_KEY` | if provider is `anthropic` | - | from https://console.anthropic.com |
| `ANTHROPIC_MODEL` | no | `claude-haiku-4-5` | any Anthropic model id |
| `PHYSIOLIVE_API_TOKEN` | recommended | - | shared secret required by the API |

Chmod the env file to `600` and own it as `root:root` - the systemd
service reads it before dropping to the `physiolive` user.
