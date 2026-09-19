# PhysioLive

Real-time physiotherapy coach on a single notebook. Runs on CPU, uses a
laptop webcam or a phone stream, scores each rep against a knowledge base
built from open physiotherapy literature, and speaks feedback in Hebrew or
English.

- **One notebook, one camera, one user.**
- **Live pose estimation** with YOLOv8s-pose (OpenVINO CPU) or MediaPipe.
- **Per-rep verdicts** from a rules engine and a small classifier.
- **Voice feedback** via `pyttsx3` (offline).
- **Retrieval-augmented feedback** from a physiotherapy corpus (added from M3).
- **Optional cloud brain** on a Google Cloud e2-micro VM (added from M4).

The full product specification lives in
[docs/product_spec.md](docs/product_spec.md).

## Status

Currently at M2 milestone: Squat exercise end-to-end. See
[docs/product_spec.md](docs/product_spec.md#11-אבני-דרך-למימוש) for the roadmap.

## Quickstart

```
python -m venv .venv
.venv\Scripts\activate            # Windows
# source .venv/bin/activate       # macOS / Linux
pip install -r requirements.txt
jupyter notebook physio_live.ipynb
```

Then Kernel > Restart & Run All. A tab opens at `http://localhost:8000`
showing the live camera with the skeleton drawn on top, rep counter, and
form feedback.

## Repository layout

```
physiolive/
  physio_live.ipynb          main notebook (Run All)
  requirements.txt           local deps
  requirements-vm.txt        cloud deps (M4+)
  src/
    app/                     local pipeline modules
      pose_gate.py           YOLO/MediaPipe wrapper, COCO-17 constants
      angles.py              joint angle math
      exercises/             per-exercise JSON configs
        squat.json
      rep_counter.py         state machine + 2-tick confirmation
      form_rules.py          deterministic form-check rules
      voice.py               pyttsx3 worker + debounce
      dashboard_server.py    threading HTTP server, MJPEG stream, JSON API
      phone_stream.py        RTSP / MJPEG source for phones
    web/                     dashboard frontend
      index.html
      app.js
      style.css
    vm/                      cloud services (M4+, not populated yet)
  data/                      gitignored: models, sessions, reference signatures
  docs/
    product_spec.md          full spec
  media/                     screenshots + gallery
```

## Data sources

- **Reference exercise videos:** professional demonstrations from
  ProPhysioClinic (YouTube). Videos are used offline to build angle
  signatures under `data/reference_signatures/`; the raw mp4 files stay
  gitignored.
- **Scientific corpus:** built from open-access physiotherapy literature
  (PubMed OA, Cochrane, PEDro metadata, NIH/CDC/WHO guidelines,
  Physiopedia CC content). Corpus construction lives in `src/vm/curator/`
  and starts at M3.

## Attribution

This is a solo research project by Or Arbeli (orarr2).
