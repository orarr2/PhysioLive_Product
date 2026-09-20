# PhysioLive VM deployment

Everything under `src/vm/` is the code and configuration that runs on
the PhysioLive Google Cloud VM (an e2-micro in the Free Tier). The VM
hosts the retrieval store, the coach LLM proxy, and the JWT auth
service; the pose estimation and rep counting stay on the user's
device.

## Files

- `physiolive.service` - systemd unit that runs `uvicorn` under the
  `physiolive` service user with `MemoryMax=700M` so the free-tier
  VM never gets OOM-killed.
- `setup.sh` - one-shot installer. Installs the apt packages, clones
  the repo, builds the venv, seeds ChromaDB from the corpus, installs
  the systemd unit, generates a JWT signing key, and configures `ufw`.
- `cloudflared.md` - step-by-step guide for exposing the service over
  HTTPS via Cloudflare Tunnel (outbound-only, no firewall ports).
- `tunnel-publisher.md` - documents the systemd path unit that catches
  fresh TryCloudflare URLs on every reboot and pushes them back into
  the GitHub Pages web app.
- `README.md` - this file.

## Quick start

On a fresh Debian 12 or 13 e2-micro VM:

```
curl -L https://raw.githubusercontent.com/orarr2/PhysioLive_Product/main/src/vm/deploy/setup.sh -o setup.sh
sudo bash setup.sh
sudo nano /etc/physiolive/env     # set GROQ_API_KEY + PHYSIOLIVE_PASSPHRASE
sudo systemctl start physiolive
curl http://127.0.0.1:8000/health
```

Then follow `cloudflared.md` to attach a public HTTPS hostname and
`tunnel-publisher.md` to auto-publish the URL to the web app.

## Environment variables (`/etc/physiolive/env`)

Coach LLM
| var | required | default | notes |
|---|---|---|---|
| `COACH_PROVIDER` | no | `groq` | `groq` or `anthropic` |
| `GROQ_API_KEY` | if provider is `groq` | - | from https://console.groq.com |
| `GROQ_MODEL` | no | `openai/gpt-oss-120b` | any Groq model id |
| `ANTHROPIC_API_KEY` | if provider is `anthropic` | - | from https://console.anthropic.com |
| `ANTHROPIC_MODEL` | no | `claude-haiku-4-5` | any Anthropic model id |

Auth
| var | required | default | notes |
|---|---|---|---|
| `PHYSIOLIVE_PASSPHRASE` | yes for passphrase route | - | plain passphrase; ok for first-boot smoke test |
| `PHYSIOLIVE_PASSPHRASE_HASH` | preferred | - | bcrypt hash of the passphrase; overrides the plain form |
| `PHYSIOLIVE_ALLOWED_EMAILS` | yes for Google route | empty | comma-separated allow list |
| `GOOGLE_OAUTH_CLIENT_ID` | recommended | - | must match `webapp/assets/config.js#googleClientId` |
| `PHYSIOLIVE_JWT_SECRET` | no | auto-generated in `/var/lib/physiolive/jwt.secret` | rotate to invalidate all tokens |
| `PHYSIOLIVE_JWT_TTL` | no | `604800` (7 days) | JWT lifetime in seconds |

Rate limits
| var | default | notes |
|---|---|---|
| `PHYSIOLIVE_LIMIT_PER_MIN` | `30/minute` | applied per key (JWT sub or IP) to every route |
| `PHYSIOLIVE_LIMIT_PER_DAY` | `500/day`   | daily cap per key |
| `PHYSIOLIVE_USER_LIMIT`    | `20/minute` | tighter cap on `/rag/query` and `/coach/feedback` |

See `docs/rate-limits.md` for the full ceiling of every layer (client,
VM, Groq, Anthropic) and how to adjust them.

Chmod the env file to `600` and own it as `root:root` - the systemd
service reads it before dropping to the `physiolive` user.
