# Rate limits

Every layer between the user's browser and the LLM applies its own
throttle. This document lists them so you can spot which one an HTTP
429 came from and adjust deliberately.

## Layer 1 - Web app (browser)

Location: `webapp/assets/coach_client.js`.

| control | value | reason |
|---|---|---|
| `MIN_GAP_MS` | 2500 ms | Do not spam the VM on rapid reps; wait 2.5s between coach fetches. |
| `REQUEST_TIMEOUT_MS` | 18000 ms | Groq's `openai/gpt-oss-120b` normally answers in 6-12 s; the abort timeout must stay above that ceiling. |

The MediaPipe pose loop is uncapped (runs at browser rAF cadence, ~15-30 fps).
Only the coach fetch is throttled.

## Layer 2 - VM API (FastAPI + slowapi)

Location: `src/vm/api.py`.

Two buckets, each keyed by JWT sub when the request is authed and by
client IP for the health check.

| route | default limit | env override |
|---|---|---|
| `GET /health`        | 60 / minute | (hardcoded) |
| `POST /auth/login`   | 10 / minute | (hardcoded) |
| `POST /auth/google`  | 10 / minute | (hardcoded) |
| `POST /rag/query`     | 20 / minute (per user) | `PHYSIOLIVE_USER_LIMIT` |
| `POST /coach/feedback`| 20 / minute (per user) | `PHYSIOLIVE_USER_LIMIT` |
| every route          | 30 / minute + 500 / day (per key)  | `PHYSIOLIVE_LIMIT_PER_MIN`, `PHYSIOLIVE_LIMIT_PER_DAY` |

On 429 the VM returns:

```json
{ "detail": "rate limit exceeded", "limit": "20 per 1 minute" }
```

The web app catches that response, keeps the rule-based verdict on
screen for the rep, and shows a `Coach rate limit hit` toast. The
next rep will try again as soon as the window rolls over.

### Adjusting

Edit `/etc/physiolive/env` and restart the service. The systemd
`EnvironmentFile=` picks up the new values on `systemctl restart
physiolive`.

```
PHYSIOLIVE_LIMIT_PER_MIN=60/minute
PHYSIOLIVE_LIMIT_PER_DAY=1000/day
PHYSIOLIVE_USER_LIMIT=30/minute
```

Do not raise these above the LLM provider's own ceiling (see below);
you will just push the 429 downstream instead of fixing the pressure.

## Layer 3 - LLM provider

### Groq free tier (default)

Values as of 2026-01 (Groq's console reflects the current numbers per
key at https://console.groq.com/settings/limits ):

| model                    | requests / min | requests / day | tokens / min |
|--------------------------|----------------|----------------|--------------|
| `openai/gpt-oss-120b`    | 30             | 1,000          | 12,000       |
| `openai/gpt-oss-20b`     | 30             | 1,000          | 30,000       |
| `qwen/qwen3-8-27b`       | 30             | 1,000          | 15,000       |
| `groq/compound-mini`     | 30             | 1,000          | 15,000       |

The coach endpoint sends about 800-1200 output tokens plus around
600-1200 input tokens per rep. That leaves headroom for roughly
7-8 reps per minute on the tokens-per-minute cap, well under the
per-user 20/minute limit above.

### Anthropic (optional fallback)

Anthropic's tier-1 free trial is capped at 5 requests per minute and
50 requests per day for Haiku. Set `COACH_PROVIDER=anthropic` and
`ANTHROPIC_API_KEY=...` in `/etc/physiolive/env`; the VM will fall
through to Anthropic when the primary provider errors.

## Layer 4 - Cloudflare tunnel (TryCloudflare)

Quick tunnels are rate-limited by Cloudflare at the edge; the exact
numbers are not published, but sustained bursts above ~50 req/sec have
been reported to trip 503s. Our VM caps sit well under that.

## Debugging a 429

1. Read `Retry-After` on the response. The VM always sends 60.
2. Check the browser DevTools Network panel for the response body
   `detail` string. Values map back to the tables above.
3. Inspect the VM's journal:

   ```
   sudo journalctl -u physiolive -n 100 --no-pager
   ```

   slowapi logs the limit key ( `u:...` for JWT sub, `ip:...` for
   unauthenticated) so you can tell which bucket is full.
4. Groq 429s bubble up as `coach LLM error: ...` in the same journal.
   The web app still shows the rule-based verdict so the live loop
   never stalls.

## Summary of ceilings (defaults)

- **1 request every 2.5 seconds** from any single browser session.
- **20 coach requests / minute per signed-in user**.
- **30 / minute + 500 / day per IP or JWT** (whichever is stricter).
- **~30 LLM requests / minute** from the VM upstream, before the Groq
  free tier itself rate-limits.
