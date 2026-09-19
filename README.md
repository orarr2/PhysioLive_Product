# PhysioLive

Real-time physiotherapy coach on a single notebook. Runs on a laptop
CPU, uses a webcam or a phone stream, counts each rep, checks form
against a scientific knowledge base, and speaks feedback out loud.

- **One notebook, one camera, one user.**
- **Rich pose overlay** with 33 body landmarks and 21 per hand (finger
  joints), rendered as a colored skeleton on top of the live video.
- **Deterministic per-rep verdicts** from a state machine and a rule
  engine, later augmented by a small classifier.
- **Voice feedback** via the system TTS engine (offline).
- **Retrieval-augmented feedback** grounded in a physiotherapy corpus.
- **Optional cloud brain** on a Google Cloud e2-micro VM (free tier)
  that hosts the vector index and proxies the language model.

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

## Repository layout

```
physiolive/
  physio_live.ipynb          main notebook (Run All)
  requirements.txt           pip dependencies
  src/
    app/                     local pipeline modules
      pose_gate.py           pose backends + skeleton drawing
      angles.py              joint angle math
      exercises/             per-exercise JSON configs
      rep_counter.py         state machine + two-tick confirmation
      form_rules.py          deterministic form-check rules
      rep_classifier.py      LightGBM ONNX rep-quality classifier
      voice.py               pyttsx3 worker + debounce
      dashboard_server.py    threading HTTP server, MJPEG stream, JSON
      phone_stream.py        RTSP / MJPEG source for phones
      session_log.py         SQLite session persistence
      rag/
        corpus.py            physiotherapy corpus ingest
        embedder.py          sentence-transformers wrapper
        store.py             ChromaDB persistent store
        query.py             retrieval + citation helper
      agents/
        analyzer.py          local rules + classifier fusion
        coach.py             LLM-narrated feedback (with citations)
        progress.py          end-of-session summary
    web/                     dashboard frontend
      index.html
      app.js
      style.css
  data/                      gitignored: models, sessions, signatures
  docs/                      design notes
```

## Pose backends

Set `pose_backend` per exercise config. Options:

| backend                | landmarks     | notes                            |
|------------------------|---------------|----------------------------------|
| `mediapipe_holistic`   | 33 body + 21 per hand | default; richest skeleton |
| `mediapipe_pose`       | 33 body       | body-only, lighter than holistic |
| `yolo`                 | 17 body (COCO)| fastest CPU path, OpenVINO ready |

The YOLO backend picks up a sibling `*_openvino_model` directory
automatically. Export once for a 2 to 3x CPU speedup:

```
python -c "from ultralytics import YOLO; YOLO('yolov8s-pose.pt').export(format='openvino', imgsz=384)"
```

## Adding a new exercise

Drop a new JSON file under `src/app/exercises/`, following the shape of
`squat.json`. The state-machine thresholds (`standing_deg`, `bottom_deg`,
`hysteresis_deg`, `confirm_frames`) drive rep counting. The `rules`
array is checked at rep-end and produces the coach's verdict.

## Data sources

- **Reference exercise videos:** professional demonstrations placed
  under `data/reference_videos/<exercise>/`. Used offline to build
  angle signatures under `data/reference_signatures/`. Raw mp4 files
  stay gitignored; only the derived JSON signatures are checked in.
- **Scientific corpus:** open-access physiotherapy sources (PubMed OA,
  Cochrane, PEDro metadata, NIH / CDC / WHO guidelines, Physiopedia
  Creative Commons content). Ingested by `src/app/rag/corpus.py` into
  a local ChromaDB.

## License

MIT. See `LICENSE`. Note that the default YOLO pose weights ship under
AGPL-3.0. For commercial redistribution switch `pose_backend` to
`mediapipe_pose` or `mediapipe_holistic` (Apache-2.0).
