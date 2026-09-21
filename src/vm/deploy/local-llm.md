# Local Llama fallback

The VM's coach primarily calls Groq's `openai/gpt-oss-120b`. Any failure
- Groq rate limit, 5xx, timeout, or a broken API key - is caught by
[`vm.coach_llm.call_llm`](../coach_llm.py) and falls through to a local
Llama 3.2 1B Instruct that lives on disk under
`/opt/physiolive/models/`. The fallback is best-effort: if the model
weights or the `llama-cpp-python` package are missing, the failure is
logged and the caller sees the original Groq exception, so the coach
endpoint drops back to the deterministic rule verdict instead of
hanging.

## Constraints

The Free Tier VM has 1 GB RAM. FastAPI + ChromaDB + cloudflared already
take ~350 MB. That leaves ~500-600 MB for the local model. Llama 3.2 1B
Q4_K_M weighs ~800 MB on disk and needs ~900-1000 MB at inference,
which is tight - the model does fit, but a stray background process
can push the service to systemd's `MemoryMax=700M` cap. Two knobs
control the pressure:

- `PHYSIOLIVE_LOCAL_LLM_CTX` (default `1024`) - context window in
  tokens. Smaller = less RAM. Drop to `768` if the service OOMs.
- `PHYSIOLIVE_LOCAL_LLM_THREADS` (default `2`) - CPU threads. The
  e2-micro is 2 vCPU (shared); leaving this at 2 uses both cores
  during inference.

Expected latency on this VM: 8-15 seconds for a single 140-token
completion. That is slower than Groq (2-4 s) but a lot better than
silence when Groq is unavailable.

If the RAM pressure is real, swap to Llama 3.2 1B Q2_K (~500 MB on
disk, ~650 MB at inference) by changing `PHYSIOLIVE_LOCAL_LLM_MODEL`
to point at that gguf instead. Quality drops noticeably but the model
never OOMs.

## Install (one-time, on the VM)

```bash
# 1. Install the llama.cpp Python bindings with prebuilt CPU wheels so
#    the e2-micro does not have to compile native code (compilation
#    would blow past the 1 GB RAM budget).
sudo -u physiolive /opt/physiolive/venv/bin/pip install \
    --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu \
    llama-cpp-python

# 2. Download the quantised model (Q4_K_M is the default). ~800 MB.
sudo -u physiolive mkdir -p /opt/physiolive/models
sudo -u physiolive curl -L \
    "https://huggingface.co/bartowski/Llama-3.2-1B-Instruct-GGUF/resolve/main/Llama-3.2-1B-Instruct-Q4_K_M.gguf?download=true" \
    -o /opt/physiolive/models/llama-3.2-1b-instruct-q4_k_m.gguf

# 3. Verify the file size (should be ~800 MB) and permissions.
ls -la /opt/physiolive/models/llama-3.2-1b-instruct-q4_k_m.gguf

# 4. Restart the service so the coach code picks the model up on
#    the first fallback.
sudo systemctl restart physiolive
```

## Smoke test

Force the fallback by pointing the coach at a bogus Groq key for a
single request:

```bash
JWT=$(curl -s -X POST http://127.0.0.1:8000/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"passphrase":"<your passphrase>","display_name":"local-test"}' \
  | jq -r .jwt)

# Coach with Groq intact - should be Groq-fast (2-4 s).
time curl -s -X POST http://127.0.0.1:8000/coach/feedback \
  -H "Authorization: Bearer $JWT" \
  -H 'Content-Type: application/json' \
  -d '{"exercise":"Squat","verdict_level":"warn",
       "verdict_text":"Shallow rep.","metrics":{"knee":110}}' | jq

# Simulate a Groq outage.
sudo systemctl edit --full physiolive
# ...change GROQ_API_KEY to something invalid, save, exit...
sudo systemctl restart physiolive

# Coach fallback - should return a real sentence from local Llama in
# 8-15 s. Watch `journalctl -u physiolive -f` for
# "coach: Groq failed ... falling through to local Llama fallback".
time curl -s -X POST http://127.0.0.1:8000/coach/feedback \
  -H "Authorization: Bearer $JWT" \
  -H 'Content-Type: application/json' \
  -d '{"exercise":"Squat","verdict_level":"warn",
       "verdict_text":"Shallow rep.","metrics":{"knee":110}}' | jq
```

Restore the real `GROQ_API_KEY` afterwards.

## Environment variables

| var | default | purpose |
|---|---|---|
| `PHYSIOLIVE_LOCAL_LLM_MODEL` | `/opt/physiolive/models/llama-3.2-1b-instruct-q4_k_m.gguf` | path to the gguf file |
| `PHYSIOLIVE_LOCAL_LLM_CTX` | `1024` | context window (tokens) |
| `PHYSIOLIVE_LOCAL_LLM_THREADS` | `2` | CPU threads for inference |
| `PHYSIOLIVE_LOCAL_LLM_MAX_TOKENS` | `140` | cap on generated tokens |

## Force local as primary

To bypass Groq entirely (for example when the account is
disabled), set:

```
COACH_PROVIDER=local
```

in `/etc/physiolive/env` and restart. `call_llm` will call the local
model directly without ever touching Groq.
