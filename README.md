# PhysioLive

Real-time physiotherapy coach on a single notebook. Runs on a laptop
CPU, uses a webcam or a phone stream, counts each rep, checks form
against a scientific knowledge base, and speaks feedback out loud.

- **One notebook, one camera, one user.**
- **Rich pose overlay** with 33 body landmarks and 21 per hand (finger
  joints), rendered as a colored skeleton on top of the live video.
- **Deterministic per-rep verdicts** from a state machine and a rule
  engine, optionally augmented by a small LightGBM classifier.
- **Voice feedback** via the system text-to-speech engine (offline).
- **Retrieval-augmented feedback** grounded in a physiotherapy corpus
  (Chroma vector store, sentence-transformers embeddings).
- **Session persistence** in SQLite plus a one-page PDF summary for the
  physiotherapist.
- **Optional coach agent** that narrates each rep with a citation-backed
  sentence via the Anthropic API.

## Quickstart

```
python -m venv .venv
.venv\Scripts\activate            # Windows
# source .venv/bin/activate       # macOS / Linux
pip install -r requirements.txt
jupyter notebook physio_live.ipynb
```

Then **Kernel > Restart & Run All**. A browser tab opens at
`http://localhost:8000` showing the live camera with the skeleton
drawn on top, a rep counter, and per-rep verdicts.

## Exercises

Five exercises ship in `src/app/exercises/`. Pick one by setting
`EXERCISE_ID` in the notebook's Step 2 cell:

| ID                    | Name                | Primary joint | Camera |
|-----------------------|---------------------|---------------|--------|
| `squat`               | Squat               | Knee          | front  |
| `lunge`               | Forward Lunge       | Front knee    | side   |
| `glute_bridge`        | Glute Bridge        | Hip           | side   |
| `leg_raise`           | Straight Leg Raise  | Hip           | side   |
| `shoulder_abduction`  | Shoulder Abduction  | Shoulder      | front  |

Add another exercise by dropping a new JSON file next to these, keeping
the same shape. The rep counter is direction-agnostic: it treats an
angle that decreases from the standing pose (squat, lunge) the same as
one that increases (shoulder abduction).

## Building the retrieval store

The repo ships with a small seed corpus of physiotherapy fundamentals
under `data/corpus_seed/`. Build the local vector index once:

```
python -m app.tools.build_index                # seed only
python -m app.tools.build_index --pubmed 25    # + 25 PubMed hits per query
```

The seed is enough for the notebook to run and cite generic sources.
The PubMed fetch pulls open-access abstracts on physiotherapy topics
into the same index; no API key required, but the run is rate-limited.

## Coach agent

Set the `ANTHROPIC_API_KEY` environment variable before starting the
notebook to enable the coach. The coach turns each rule verdict into a
single sentence grounded in the top retrieval chunks and only cites
sources it was actually given. Without the key, the pipeline still runs
and speaks the plain rule message.

## Rep-quality classifier

An optional LightGBM ONNX classifier at `data/models/rep_clf.onnx`
scores each finished rep as `good`, `nit`, or `wrong` on top of the
deterministic rules. To train one from a labeled CSV of past reps:

```
python -m app.tools.train_rep_classifier data/labels/reps.csv \
    --out data/models/rep_clf.onnx
```

Without the file the pipeline falls back to rules only.

## Session history

Every rep is written to `data/sessions/physiolive.db`. The dashboard's
Session tab shows the reps of the current session with per-rep angle
minima and verdicts; the Progress tab shows the last thirty sessions.
The notebook's last cell writes a one-page PDF summary next to the
database so a physiotherapist can review the session offline.

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
physiolive/
  physio_live.ipynb          main notebook (Run All)
  requirements.txt           pip dependencies
  src/
    app/
      pose_gate.py           pose backends + skeleton drawing
      angles.py              joint angle math
      exercises/             per-exercise JSON configs
      rep_counter.py         state machine + two-tick confirmation
      form_rules.py          deterministic form-check rules
      rep_classifier.py      LightGBM ONNX rep-quality classifier
      voice.py               TTS worker + debounce
      dashboard_server.py    threading HTTP server, MJPEG + JSON API
      phone_stream.py        RTSP / MJPEG source for phones
      session_log.py         SQLite session persistence
      rag/
        embedder.py          sentence-transformers wrapper
        store.py             ChromaDB persistent store
        corpus.py            seed + PubMed ingestion
        query.py             retrieval + citation helper
      agents/
        coach.py             LLM-narrated feedback with citations
        progress.py          end-of-session summary + PDF export
      tools/
        build_index.py       ingest and embed the corpus
        train_rep_classifier.py  train the LightGBM classifier
    web/
      index.html
      app.js
      style.css
  data/
    corpus_seed/             pre-cleaned physiotherapy chunks
    reference_signatures/    per-exercise angle signatures
    reference_videos/        raw demo videos (gitignored)
    models/                  ONNX classifier weights (gitignored)
    sessions/                SQLite DB + PDF exports (gitignored)
    chroma/                  vector index (gitignored)
```

## License

MIT. See `LICENSE`. Note that the default YOLO pose weights ship under
AGPL-3.0. For commercial redistribution switch `pose_backend` to
`mediapipe_pose` or `mediapipe_holistic` (Apache-2.0).
