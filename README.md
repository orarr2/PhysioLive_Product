# PhysioLive

Real-time physiotherapy coach that runs where the user is: in their
own browser, or in a single-notebook desktop app. PhysioLive tracks the
user's body with on-device pose estimation, counts reps with a
direction-agnostic state machine, checks form with deterministic rules,
and turns each verdict into a citation-backed sentence using a small
retrieval-augmented LLM hosted on a free-tier VM.

> Hebrew walkthrough: see [docs/GUIDE_HE.md](docs/GUIDE_HE.md) for a
> section-by-section, right-to-left guide to the whole project.

Nothing about the user's video ever leaves the device. Only short,
already-derived summaries (rep verdict, joint-angle minima) reach the
coach service.

## Two ways to run it

**Web app (recommended).** GitHub Pages hosts a browser build at
[https://orarr2.github.io/PhysioLive_Product/](https://orarr2.github.io/PhysioLive_Product/).
It uses MediaPipe Tasks Vision for pose, keeps every camera frame local,
and calls a small FastAPI service on a Google Cloud e2-micro VM (via a
Cloudflare tunnel) for LLM-composed coaching. The web app is
sign-in gated - Google Sign-In or an invite passphrase - so the shared
LLM budget cannot be drained by strangers.

**Desktop notebook.** `physio_live.ipynb` runs the same pipeline on a
laptop CPU with a webcam or a phone stream. Useful when the VM is
offline, when you want to record a session end to end, or when you
want to inspect the intermediate data (per-frame angles, per-rep
verdicts, retrieval hits).

## Architecture

```
Browser  ---- MediaPipe Pose (33 landmarks) ----+  local, no upload
              rep counter + form rules          |
              [JWT bearer]                      |
                    |                           |
                    v                           |
        Cloudflare Tunnel (HTTPS)               |
                    |                           |
                    v                           |
     Google Cloud e2-micro VM (Free Tier)       |
       FastAPI  +  ChromaDB (ONNX embed)  <-----+  short verdict summary
       + Groq LLM (openai/gpt-oss-120b)                   arrives here
                    |
                    v
       coaching sentence + citation URL
                    |
                    v
       Web app renders + speaks feedback
```

Nothing on the VM stores raw video. The only inputs that reach it are:

- `exercise`, `verdict_level`, `verdict_text`, a few joint-angle
  numbers, and the JWT of the signed-in user.

## Quick start (web app)

1. Open [https://orarr2.github.io/PhysioLive_Product/](https://orarr2.github.io/PhysioLive_Product/).
2. Sign in - either with Google (if your email is on the allow list)
   or with the invite passphrase from the operator.
3. Pick an exercise and allow camera access.
4. On a phone with multiple cameras, use the picker in the top-left of
   the live view to switch between front, back, and any external
   webcam. Your choice is remembered locally.
5. Perform reps. The HUD ring fills as reps complete, the coach banner
   speaks each cue, and the source link lets you inspect the evidence.

## Quick start (desktop notebook)

```
python -m venv .venv
.venv\Scripts\activate            # Windows
# source .venv/bin/activate       # macOS / Linux
pip install -r requirements.txt
jupyter notebook physio_live.ipynb
```

Then **Kernel -> Restart and Run All**. A browser tab opens at
`http://localhost:8000` showing the live camera with a skeleton
overlay, a rep counter, and per-rep verdicts.

## Exercises

Five rehabilitation exercises ship in `src/app/exercises/`:

| ID                    | Name                | Primary joint | Suggested camera |
|-----------------------|---------------------|---------------|------------------|
| `squat`               | Squat               | Knee          | front            |
| `lunge`               | Forward Lunge       | Front knee    | side             |
| `glute_bridge`        | Glute Bridge        | Hip           | side             |
| `leg_raise`           | Straight Leg Raise  | Hip           | side             |
| `shoulder_abduction`  | Shoulder Abduction  | Shoulder      | front            |

Add another exercise by dropping a JSON file next to these, keeping
the same shape. The rep counter is direction-agnostic: it treats an
angle that decreases from the standing pose (squat, lunge) the same
as one that increases (shoulder abduction).

## Scientific corpus

`corpus/` is the physiotherapy evidence the coach cites from. It ships
in two layers:

- **Seed layer** (~15 hand-authored chunks). Committed to git under
  `corpus/{squat,knee,hip,shoulder,general}/chunks.json`. Optimised
  for the specific rules the app enforces.
- **PubMed layer** (500-700 chunks after ingest). Grown on demand
  from ~24 physiotherapy queries against NCBI E-utilities. Lives only
  in the ChromaDB files on each install; kept out of git so we do not
  redistribute third-party abstract text.

Every chunk carries its own source URL, license and evidence level so
the web app can surface them next to each coach message.

- `corpus/README.md` - full overview and methodology.
- `corpus/INDEX.md`  - seed-layer table + how to size the PubMed layer.
- `corpus/CONTRIBUTING.md` - how to add or update evidence.
- `src/app/rag/pubmed_queries.py` - the PubMed query set.

Build the local vector index:

```
python -m app.tools.build_index                # seed only (~15 chunks)
python -m app.tools.build_index --pubmed 25    # +25 abstracts per query
                                               # (~500-700 chunks total)
```

Verify the total count:

```
python -c "from app.rag.store import Store; print(Store().count_evidence())"
```

## Web app

- Source: `webapp/` (GitHub Pages source is `main:/webapp`).
- Deploy: pushed to `main` triggers `.github/workflows/pages.yml`.
- Runtime config: `webapp/assets/config.js` (hardcoded fallback) plus
  `webapp/tunnel-url.json` (auto-updated by the VM on tunnel restart).
- Auth: JWT issued by the VM. See `docs/deployment.md` for the
  passphrase and Google Sign-In wiring.
- See `webapp/README.md` for the module-by-module layout.

## VM service

- Source: `src/vm/api.py`, `src/vm/auth.py`, `src/vm/coach_llm.py`.
- Deploy: `sudo bash src/vm/deploy/setup.sh` on a fresh Debian 12 e2-micro.
- Systemd: `physiolive.service` runs with `MemoryMax=700M` so the free
  tier VM never gets OOM-killed.
- Cloudflared: `src/vm/deploy/cloudflared.md`.
- Tunnel URL auto-publisher: `src/vm/deploy/tunnel-publisher.md`.
- Full environment reference: `src/vm/deploy/README.md`.

## Rate limits

`docs/rate-limits.md` documents every layer:

- Web app throttles requests to the VM at 1 per 2.5 seconds.
- VM enforces per-IP (30/minute, 500/day) and per-user (20/minute,
  300/day) limits; 429 responses fall through to the deterministic
  rule text so the live loop keeps moving.
- Groq free tier is capped at 30 requests per minute for
  `openai/gpt-oss-120b` and lower for daily volume; the same doc lists
  the current thresholds and how to raise them.

## Rep-quality classifier

An optional LightGBM ONNX classifier at `data/models/rep_clf.onnx`
scores each finished rep as `good`, `nit`, or `wrong` on top of the
deterministic rules. Train from a labelled CSV:

```
python -m app.tools.train_rep_classifier data/labels/reps.csv \
    --out data/models/rep_clf.onnx
```

Without the file the pipeline falls back to rules only.

## Session history

Every rep is written to `data/sessions/physiolive.db` (desktop) or
`localStorage` (web app). The dashboard's Session tab shows the reps
of the current session; the Progress tab shows the last thirty
sessions. The notebook's last cell writes a one-page PDF summary next
to the database so a physiotherapist can review the session offline.

## Pose backends

Set `pose_backend` per exercise config. Options:

| backend                | landmarks               | notes                                  |
|------------------------|-------------------------|----------------------------------------|
| `mediapipe_holistic`   | 33 body + 21 per hand   | default; richest skeleton              |
| `mediapipe_pose`       | 33 body                 | body-only, lighter than holistic       |
| `yolo`                 | 17 body (COCO)          | fastest CPU path, OpenVINO ready       |

The YOLO backend picks up a sibling `*_openvino_model` directory
automatically. Export once for a 2 to 3x CPU speedup:

```
python -c "from ultralytics import YOLO; YOLO('yolov8s-pose.pt').export(format='openvino', imgsz=384)"
```

## Repository layout

```
PhysioLive_Product/
  physio_live.ipynb          main desktop notebook (Run All)
  requirements.txt           desktop pip dependencies
  src/
    app/                     shared library (pose, rules, RAG, agents)
    vm/                      FastAPI service that runs on the VM
      api.py                 endpoints (health, auth, rag, coach)
      auth.py                JWT + Google + passphrase
      coach_llm.py           Groq / Anthropic caller
      requirements.txt       slim VM dependencies
      deploy/                setup.sh, systemd units, cloudflared docs
  webapp/                    GitHub Pages source
    index.html
    tunnel-url.json          auto-updated on tunnel restart
    assets/                  app.js, pose.js, rules.js, ...
  corpus/                    scientific corpus (topic-per-folder)
  data/
    corpus_seed/             legacy seed corpus (read for backward compat)
    reference_signatures/    per-exercise angle signatures
    reference_videos/        raw demo videos (gitignored)
    models/                  ONNX classifier weights (gitignored)
    sessions/                SQLite DB + PDF exports (gitignored)
    chroma/                  vector index (gitignored)
  docs/
    rate-limits.md
    deployment.md
  .github/workflows/pages.yml    GitHub Pages deployment
```

## License

MIT. See `LICENSE`. Note that the default YOLO pose weights ship
under AGPL-3.0. For commercial redistribution switch `pose_backend`
to `mediapipe_pose` or `mediapipe_holistic` (Apache-2.0).
