# ST-GCN Migration Plan: From Rule-Based Angles to Skeleton-Aware Deep Learning

**Status:** Planning (no implementation started).
**Owner:** orarr2.
**Last updated:** 2026-09-23.

---

## 0. Executive Summary

Today the coach pipeline reduces every camera frame to six scalar joint
angles and then applies deterministic `if/else` rules. That representation
throws away ~93% of the spatial information the pose detector already
extracts, discards the temporal shape of each rep, and never uses the
3D world-coordinate output MediaPipe provides. It also makes real
learning impossible: there is nothing to train on except a hand-crafted
feature vector.

This plan migrates the pipeline to a **skeleton-aware, temporally-aware
representation** grounded in an established public benchmark
(**UI-PRMD**, the University of Idaho Physical Rehabilitation Movement
Dataset) and a well-known model family (**ST-GCN**, Spatio-Temporal
Graph Convolutional Networks, Yan et al. AAAI 2018). The end state is:

* Per-rep tensors of shape `(C, T, V, M)` retained and logged.
* A trained ST-GCN classifier on UI-PRMD that generalises to our
  MediaPipe-driven live capture through a common canonical skeleton.
* Per-joint attribution ("the right knee dominated the wrong-rep
  verdict") surfaced to the coach LLM instead of a single boolean.
* Camera-perspective independence via root-centered 3D coordinates.

No code changes are executed as part of this document; every phase is
scoped so a single engineer can pick it up and implement it in isolation.

---

## 1. Current State (Baseline)

### 1.1 Data pipeline as of `main@5cf48ce`

```
frame  ->  MediaPipe / YOLO           (17 or 33 keypoints, 2D px + conf)
       ->  angles.py                   (6 scalar angles: knee_L/R,
                                        hip_L/R, elbow_L/R, shoulder_L/R,
                                        torso_vertical, knee_over_toe)
       ->  rep_counter.py              (8 summary stats per rep:
                                        min/max/rom/tempo/torso_max/
                                        knee_over_toe_max)
       ->  form_rules.py               (rule-based verdict:
                                        good / nit / warn / wrong)
       ->  RAG + LLM                   (verdict summary -> coach sentence)
```

### 1.2 What is discarded before any learning could see it

| Signal                | Available from MediaPipe | Kept by current pipeline |
|-----------------------|:-------------------------:|:--------------------------:|
| 2D pixel landmarks    | 33 x (x, y, conf)         | Only used to compute 6 angles |
| 3D world landmarks    | 33 x (x, y, z) meters, hip-centered | **Not used at all** |
| Per-frame time series | Continuous while camera is on | Only summary stats per rep |
| Velocity, jerk        | Derivable from time series | **Not computed** |
| Inter-joint dependencies | Native to skeleton graph | Each angle computed independently |

### 1.3 What "learning" currently exists in the repo

* `src/app/tools/train_rep_classifier.py` - a LightGBM stub that would
  take a labelled CSV of 15 tabular features and output `good/nit/wrong`.
  Never trained: `data/models/` is empty and `data/labels/reps.csv` does
  not exist. The pipeline falls back to rules.
* No sequence model. No skeleton model. No public benchmark ever loaded.

### 1.4 Perspective problem

The 2D-pixel path is intrinsically camera-dependent: rotate the phone
30 degrees and every angle changes. The rules paper over this with
tolerances, but a model trained on the same 2D pixels would inherit the
same fragility. This is the single biggest correctness risk in the
current architecture and the primary motivation for the migration.

---

## 2. Motivation

### 2.1 Why UI-PRMD

* Public, licensable, widely cited rehab-movement benchmark.
* 10 movements chosen for physiotherapy screening (deep squat, hurdle
  step, inline lunge, side lunge, sit-to-stand, active straight-leg
  raise, shoulder abduction, shoulder extension, shoulder internal-
  external rotation, shoulder scaption). **Seven of the ten overlap
  directly with the five exercises PhysioLive currently ships.**
* 10 healthy subjects x 10 correct + 10 incorrect repetitions per
  movement = up to 2,000 labelled reps.
* Ground-truth skeletons captured from both a **Kinect V2 (25 joints)**
  and a **Vicon marker set (39 joints)** in 3D world coordinates -
  eliminating pose-detector noise from the training signal.
* Comparable baselines already published on the same set (LSTMs, GRUs,
  simple GCNs, ST-GCN variants), so any thesis-worthy result has a peer
  reference to cite.

### 2.2 Why ST-GCN

* Input tensor `(N, C, T, V, M)` is the natural home for the data we
  currently throw away: `C=3` for `(x, y, z)`, `T=` frames per rep,
  `V=` joints in the canonical skeleton, `M=1` person.
* Operates on the skeleton **as a graph**, which encodes the physical
  adjacency of joints (knee is connected to hip and ankle, not to the
  wrist). This is a strictly stronger prior than "each angle in
  isolation".
* Temporal convolutions capture the *shape* of the movement, not only
  its endpoints. Distinguishing a controlled 3-second eccentric from a
  fast drop-and-bounce is impossible with min/max features and trivial
  with a temporal model.
* Attention / class activation mapping on graph nodes yields **per-joint
  attribution**, which the coach LLM can surface as physiotherapy-
  grade feedback ("your right knee drove the wrong-rep verdict"),
  replacing today's opaque scalar verdict.
* ONNX-exportable. A trained ST-GCN is small (3-10 MB) and inferences
  in single-digit milliseconds on CPU, comfortably within the free-tier
  VM's budget.

### 2.3 Why now

The rule-based ceiling is visible in every user session: rules cannot
express "this rep is technically in range but the tempo profile
suggests compensation." A learning system trained on labelled reps can.
UI-PRMD makes it possible to bootstrap the learning system without
first running a data-collection campaign; the campaign then extends
what UI-PRMD already covers.

---

## 3. Target Architecture

```
frame  ->  MediaPipe Pose Landmarker        (33 x world_landmarks in 3D)
       ->  skeleton_mapper.py                (33 -> canonical 17)
       ->  landmark_buffer.py                (ring buffer, per rep)

           on rep close:
           ------------
           tensor  (3, T, 17, 1)              <- persisted per rep

       ->  st_gcn_infer                       (ONNX Runtime, <=10 ms)
              output: class probs + per-joint saliency

       ->  coach LLM (RAG unchanged)          <- receives class + saliency
                                                  as structured verdict
```

Training (offline, one-off, GPU box or Colab):

```
UI-PRMD (Kinect 25 xyz)  ->  kinect25_to_canonical17.py
                         ->  ST-GCN training (PyTorch)
                         ->  ONNX export
                         ->  bundle into VM deploy tree at
                             data/models/st_gcn_rep_clf.onnx
```

---

## 4. Phased Roadmap

Each phase is independently valuable, independently testable, and
ordered so that the pipeline is always shippable after every phase.

### Phase 0 - Prerequisites

* Confirm UI-PRMD licensing allows redistribution of derived tensors
  (it does; the licence is "free for research and educational use with
  citation"). Add the citation line to `README.md`.
* Reserve a GPU-capable environment for training (Colab Pro or a
  personal RTX 30-series box). CPU-only training on the full set takes
  overnight but is feasible.
* Pin the exact MediaPipe Tasks Vision version in both the web app
  (`webapp/assets/pose.js`) and the desktop notebook so that the
  canonical skeleton mapping is reproducible.

**Exit criterion:** licence text pasted, environment reachable,
MediaPipe version noted in `docs/deployment.md`.

### Phase 1 - Preserve Raw Landmarks (No Model Yet)

Goal: stop discarding data. The rules keep working; we merely start
retaining the tensor a future model will need.

* `src/app/pose_gate.py`:
  * Add a `world_landmarks: list[tuple[float, float, float, float]] | None`
    field to `PoseFrame` (x, y, z in meters, visibility 0-1).
  * Populate it from MediaPipe's `pose_world_landmarks`. YOLO backend
    returns `None` for this field.

* `src/app/rep_counter.py`:
  * Add a per-rep ring buffer that collects the world_landmarks for
    every frame between `STANDING -> BOTTOM` and rep close.
  * On rep-close event, emit the buffered sequence alongside the
    existing summary stats.

* New module `src/app/rep_tensor.py`:
  * Function `to_tensor(sequence) -> np.ndarray` with shape
    `(3, T, 17, 1)`.
  * Uses the canonical 17-joint layout defined in Phase 2.
  * Normalises: (a) root-center to the hip midpoint, (b) scale by
    torso length so subject height is factored out.

* New module `src/app/tools/dump_rep_tensors.py`:
  * CLI that consumes the notebook or a captured session and writes
    `.npy` files under `data/rep_tensors/<exercise>/`.
  * Each file carries a sidecar JSON with the deterministic verdict
    (`good/nit/warn/wrong`) so we start building an in-house labelled
    set even before UI-PRMD lands.

**Exit criterion:** after a 5-rep squat notebook run,
`data/rep_tensors/squat/` contains five `.npy` files that load into
NumPy with the correct shape and finite values.

### Phase 2 - Canonical Skeleton Definition and Mapping

Goal: define one skeleton the entire codebase agrees on and provide
lossless mappers from every source layout we care about.

* Choose canonical layout: **17 joints, COCO-style ordering**. Reason:
  MediaPipe -> COCO-17 is a well-documented lossy reduction (drops
  face detail, keeps everything limb-relevant), and every ST-GCN
  reference implementation ships weights or configs for COCO-17.

* New file `src/app/skeletons/canonical17.py`:
  * Constants for joint indices and the edge list (skeleton graph).
  * `MEDIAPIPE33_TO_CANONICAL17` mapping table.
  * `KINECT25_TO_CANONICAL17` mapping table (see Table 2 below).
  * `VICON39_TO_CANONICAL17` mapping table (optional; UI-PRMD Vicon
    stream is more accurate than Kinect but higher-dimensional).
  * Unit tests that (a) every canonical joint has a source in each
    mapping, (b) parent-child relationships in the graph are preserved.

**Exit criterion:** a round-trip test loads a UI-PRMD Kinect frame,
maps to canonical17, and asserts that the knee-hip-ankle triangle
matches the ground-truth angle within 1 degree.

### Phase 3 - UI-PRMD Ingest

Goal: bring UI-PRMD onto the training machine in the canonical tensor
format.

* New module `src/app/data/ui_prmd.py`:
  * Downloader that fetches the raw archive from the University of
    Idaho hosting URL and verifies the checksum. **The raw data is
    gitignored**; only the derived tensors and index files are
    checked in, mirroring the PubMed corpus policy.
  * Parser that reads the position files (Kinect and, optionally,
    Vicon) into `(C=3, T, V=25, M=1)` NumPy arrays.
  * `to_canonical17` reducer that applies the Phase-2 mapping.
  * Emits an index CSV: `subject_id, movement_id, rep_id, tensor_path,
    label` where `label` is `correct` or `incorrect` per UI-PRMD's own
    binary annotation.

* Held-out split: **Leave-One-Subject-Out (LOSO)** cross-validation.
  Reason: rep-level or random splits leak subject-specific gait into
  the test set and inflate accuracy. LOSO is the correct protocol for
  this class of dataset and every peer paper on UI-PRMD uses it.

**Exit criterion:** `python -m app.data.ui_prmd --stats` prints the
tensor count (~2000), average `T`, and confirms the label balance.

### Phase 4 - Baseline Models (Pre-ST-GCN)

Goal: quantify what we should beat before spending compute on ST-GCN.
This is *the* thesis-quality contribution and must not be skipped.

* **Baseline A:** current deterministic rules run against UI-PRMD reps
  after canonical mapping. Report per-movement accuracy, precision,
  recall on the `correct/incorrect` label.
* **Baseline B:** LightGBM on the existing 15 tabular features
  (finally training `train_rep_classifier.py` end-to-end).
* **Baseline C:** 1D CNN or small LSTM over the flattened
  `(3 * 17, T)` sequence, no graph structure.

* Report all four numbers (A, B, C, ST-GCN) in a single table in the
  final write-up. This is the honest way to argue that the graph
  structure is doing work rather than the deep model tautologically
  beating a hand-crafted rule.

**Exit criterion:** `results/baselines.md` contains a LOSO table
covering A, B, C across all 10 UI-PRMD movements.

### Phase 5 - ST-GCN Training

Goal: train an ST-GCN on UI-PRMD, LOSO, and export ONNX.

* Adopt a reference implementation. Two candidates:
  * `mmskeleton` (OpenMMLab) - modern, actively maintained, integrates
    cleanly with PyTorch Lightning.
  * `st-gcn` (Yan et al. original) - closer to the paper, simpler to
    read, less maintained.
  * **Recommendation:** `mmskeleton` for the training run, but keep the
    inference-time forward pass as a self-contained module we own, so
    we do not take a runtime dependency on the whole framework.

* Config:
  * Canonical 17-joint skeleton with the edge list from
    `canonical17.py`.
  * `C=3, V=17, M=1`, `T=64` after uniform temporal resampling.
  * Learning rate 0.01 with cosine annealing, batch 32, 80 epochs.
  * Class-balanced sampling (UI-PRMD is roughly balanced but per-
    movement subsets are not).

* Output artefacts:
  * `data/models/st_gcn_rep_clf.pt` (PyTorch checkpoint, gitignored).
  * `data/models/st_gcn_rep_clf.onnx` (deployable, gitignored,
    downloaded by the VM's setup script from a release asset).

* Evaluation report `results/st_gcn.md`:
  * LOSO mean accuracy and confusion matrix.
  * Per-movement breakdown (some movements will be easier than
    others).
  * Per-joint saliency example figures so the qualitative claim
    ("model focuses on the knee for squat verdicts") is defensible.

**Exit criterion:** ONNX file loads in `onnxruntime`, inference runs
in <=10 ms on the free-tier VM CPU, LOSO accuracy meaningfully beats
Baselines A/B/C (target: at least +5 percentage points over the best
baseline).

### Phase 6 - Runtime Integration

Goal: put the trained model behind the live coach path without
disturbing the rest of the stack.

* New endpoint `POST /classify_rep` on the VM (`src/vm/api.py`):
  * Input: `{ exercise, tensor_b64, subject_height_cm }`.
  * Output: `{ class, class_probs, per_joint_saliency }`.
  * Rate-limited on the same buckets as the existing `/coach` route.

* Webapp change:
  * `webapp/assets/pose.js` starts buffering `world_landmarks` per
    rep once the model is enabled.
  * `webapp/assets/app.js` posts the tensor on rep close, in parallel
    with the existing summary post, gated by a `feature.st_gcn` flag
    in `config.js` so we can dark-launch it.

* Coach prompt (`src/vm/coach_llm.py`):
  * Add the per-joint saliency map to the retrieval query.
  * Update the system prompt to instruct the LLM to name the joint
    with the highest saliency in its coaching sentence.

* Fallback: if `/classify_rep` returns 5xx or is disabled, the rules
  path stays authoritative. This is a strict superset - nothing gets
  worse if the model is unreachable.

**Exit criterion:** a live squat session on the deployed webapp shows
model-driven verdicts and per-joint attribution, with the rule path
still visible in the console log for A/B comparison.

### Phase 7 - Data Extension (Optional, Post-Thesis)

* Ethics-first data collection at partner clinics or with a small
  paid volunteer cohort.
* Camera protocol standardisation (fixed distance, tripod height,
  front-and-side dual capture) so the field data matches the training
  distribution.
* Inter-rater agreement measurement (Cohen's kappa) between at least
  two physiotherapists on a shared subset before any physio label is
  trusted.
* Class-balance strategy: intentionally collect biased executions,
  or apply focal loss / class weights, to avoid a 90/10 correct/
  incorrect degenerate split.

---

## 5. Skeleton Mapping Tables

### 5.1 Canonical 17-joint layout

Adopted directly from COCO-17. Ordering fixed to:

```
 0 nose            9  right_wrist
 1 left_eye        10 left_hip
 2 right_eye       11 right_hip
 3 left_ear        12 left_knee
 4 right_ear       13 right_knee
 5 left_shoulder   14 left_ankle
 6 right_shoulder  15 right_ankle
 7 left_elbow      16 (hip_midpoint, derived; used as root)
 8 right_elbow
```

Edge list (skeleton graph, undirected):
`(0,1) (0,2) (1,3) (2,4) (5,7) (7,9) (6,8) (8,10) (5,6) (5,11) (6,12)
 (11,12) (11,13) (13,15) (12,14) (14,16*) (11,16*) (12,16*)`

`16` is the derived root at hip midpoint; every training tensor is
centered on this joint before being fed to the model.

### 5.2 Kinect V2 (25) -> canonical 17

| UI-PRMD Kinect index | Kinect name          | Canonical17 index |
|:---:|:---|:---:|
|  0 | SpineBase              | (used to derive 16) |
|  1 | SpineMid               | drop |
|  2 | Neck                   | drop |
|  3 | Head                   |  0 (nose approx) |
|  4 | ShoulderLeft           |  5 |
|  5 | ElbowLeft              |  7 |
|  6 | WristLeft              |  9 |
|  7 | HandLeft               | drop |
|  8 | ShoulderRight          |  6 |
|  9 | ElbowRight             |  8 |
| 10 | WristRight             | 10 |
| 11 | HandRight              | drop |
| 12 | HipLeft                | 11 |
| 13 | KneeLeft               | 13 |
| 14 | AnkleLeft              | 15 |
| 15 | FootLeft               | drop |
| 16 | HipRight               | 12 |
| 17 | KneeRight              | 14 |
| 18 | AnkleRight             | 16 (right-ankle slot; note left-right note below) |
| 19 | FootRight              | drop |
| 20 | SpineShoulder          | drop |
| 21-24 | HandTip/Thumb, L/R  | drop |

Left-right convention: canonical 17 uses **subject-anatomical** left
and right, not camera-mirror. UI-PRMD is already anatomical, so the
mapping is direct. MediaPipe's `_left` / `_right` fields are also
anatomical (documented in the MP Tasks Vision docs), so the two agree.

Note on eyes/ears (canonical indices 1-4): Kinect does not provide
these. Fill with `NaN` at ingest and mask them in the loss during
training so the model never learns to depend on them. This preserves
the option of using MediaPipe's richer head landmarks at inference
without retraining.

### 5.3 MediaPipe 33 -> canonical 17

MediaPipe indices from the Pose Landmarker documentation:

| MP idx | MP name              | Canonical17 index |
|:---:|:---|:---:|
|  0 | nose                   |  0 |
|  2 | left_eye               |  1 |
|  5 | right_eye              |  2 |
|  7 | left_ear               |  3 |
|  8 | right_ear              |  4 |
| 11 | left_shoulder          |  5 |
| 12 | right_shoulder         |  6 |
| 13 | left_elbow             |  7 |
| 14 | right_elbow            |  8 |
| 15 | left_wrist             |  9 |
| 16 | right_wrist            | 10 |
| 23 | left_hip               | 11 |
| 24 | right_hip              | 12 |
| 25 | left_knee              | 13 |
| 26 | right_knee             | 14 |
| 27 | left_ankle             | 15 |
| 28 | right_ankle            | 16 |

Every other MediaPipe joint (hand landmarks 17-22, foot landmarks
29-32, sub-face indices 1, 3, 4, 6, 9, 10) is dropped.

---

## 6. Data Contracts

### 6.1 Per-rep tensor on disk

* Path: `data/rep_tensors/<exercise>/<session_id>/<rep_index>.npy`
* dtype: `float32`
* Shape: `(3, T, 17, 1)`
* Coordinate frame: root-centered on canonical joint 16 (hip midpoint).
* Scale: divided by the subject's torso length at the reference frame
  (first frame of the rep). Unitless after normalisation.
* Missing joints: `NaN` (not zero). The loss and inference paths must
  mask these explicitly.

### 6.2 Sidecar JSON

* Path: same stem, `.json` extension.
* Fields:
  ```json
  {
    "exercise": "squat",
    "rep_index": 3,
    "session_id": "2026-09-23T15-12-04Z-a7f2",
    "source": "mediapipe_pose",
    "canonical_version": "canonical17@v1",
    "t_frames": 62,
    "fps": 30.0,
    "rule_verdict": "warn",
    "rule_metrics": {"knee_min_deg": 78.4, "torso_max_deg": 44.1},
    "subject_height_cm": null,
    "notes": ""
  }
  ```

### 6.3 UI-PRMD derived index

* Path: `data/ui_prmd/index.csv`
* Columns: `subject_id, movement_id, rep_id, correctness, tensor_path,
  t_frames`.
* `correctness` in `{correct, incorrect}` (UI-PRMD's own binary
  labelling).

---

## 7. Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|:---:|:---:|---|
| MediaPipe world_landmarks noisy on a phone camera | High | Medium | Train with heavy noise augmentation on UI-PRMD tensors (Gaussian jitter, temporal dropout). Explicitly evaluate the model on MediaPipe-captured reps before shipping. |
| UI-PRMD movements do not exactly match our exercise definitions | Medium | Medium | For the initial ST-GCN, restrict to the seven movements that map cleanly. Ship rules-only for the other three exercises until we have our own labelled data. |
| Kinect vs MediaPipe skeleton drift at inference time | Medium | High | The canonical-17 layer is the entire point. Add a unit test that computes the same joint angle from a Kinect rep and its MediaPipe re-capture and asserts agreement within a tolerance. |
| LOSO accuracy plateaus below Baseline C | Low | High | This would falsify the "graph structure helps" claim; still worth publishing as a negative result. Backup plan: fall back to Baseline C (1D CNN) as the production model. |
| Per-joint saliency is noisy and misleads the coach LLM | Medium | Medium | Threshold saliency and require a minimum margin before naming a joint. Add a red-team test on synthetic reps where the "wrong" joint is known. |
| Free-tier VM cannot serve ONNX in time budget | Low | Low | ST-GCN models under 10 MB with `T=64` run comfortably; measured on similar hardware. If it slips, quantise to int8 (ONNX Runtime supports this out of the box). |
| Licensing violation on UI-PRMD redistribution | Low | High | Do not redistribute raw UI-PRMD in git. Only derived tensors, and only if the licence permits. Cite in `README.md` and `docs/deployment.md`. |

---

## 8. Success Metrics

### 8.1 Technical

* **Primary:** ST-GCN LOSO accuracy on UI-PRMD `correct/incorrect`
  binary label >= 85%, and >= Baseline C + 5 percentage points.
* **Secondary:** end-to-end p95 latency for `/classify_rep` <=150 ms
  from the browser's send to the VM's response, on the free-tier
  e2-micro instance.
* **Secondary:** per-joint saliency reproducibility - top-1 salient
  joint stable across 5 repetitions of the same rep by the same
  subject in at least 80% of cases.

### 8.2 Product

* Coach messages naming a specific joint ("your right knee ...") on
  at least 70% of `warn` and `wrong` verdicts.
* Rule-only fallback path continues to serve 100% of requests when the
  model is disabled or returns an error.

### 8.3 Thesis

* A four-way baseline table (rules, LightGBM, 1D CNN, ST-GCN) with
  LOSO cross-validation.
* At least one per-joint saliency figure per exercise for the write-up.
* Reproducibility: full training pipeline runs from a clean checkout
  with a single `python -m app.training.st_gcn --train` invocation
  after the UI-PRMD download step.

---

## 9. Estimated Effort

Estimates are engineer-days for a single implementer familiar with
PyTorch and this codebase. They assume no blocking on external
approvals.

| Phase | Effort | Wall time |
|:---:|:---:|:---:|
| 0 - Prereqs                           | 0.5 d | 1 d |
| 1 - Preserve landmarks                | 2 d   | 3 d |
| 2 - Canonical skeleton                | 1 d   | 1 d |
| 3 - UI-PRMD ingest                    | 2 d   | 3 d |
| 4 - Baselines A/B/C                   | 3 d   | 5 d |
| 5 - ST-GCN training + ONNX            | 4 d   | 7 d (incl. GPU wait) |
| 6 - Runtime integration               | 2 d   | 3 d |
| 7 - Data extension (optional)         | open  | months |

Total for shippable v1 (phases 0-6): ~14.5 engineer-days,
~3 calendar weeks including reviews and GPU wait.

---

## 10. Out of Scope

The following are deliberately excluded from this plan to keep it
tractable:

* End-to-end video learning (RGB pixel -> verdict). Rejected in favor
  of the pose-first path for reasons discussed in Section 1.4 and 2.2.
* Re-training the pose detector itself. MediaPipe and YOLO are already
  strong on the general-population distribution we care about; the
  marginal gain from fine-tuning is dominated by the marginal gain
  from adding a temporal-graph classifier on top.
* Multi-person tracking. `M=1` throughout; `M>1` is a future
  extension.
* 6-DOF camera calibration. The 3D world-coordinate output from
  MediaPipe is good enough for the accuracy target set in Section 8.
* Live streaming to a physiotherapist dashboard. The session history
  path in `data/sessions/` already covers async review.

---

## 11. References

* Yan, S., Xiong, Y., Lin, D. *Spatial Temporal Graph Convolutional
  Networks for Skeleton-Based Action Recognition.* AAAI 2018.
  `arXiv:1801.07455`.
* Vakanski, A., Jun, H.-p., Paul, D., Baker, R. *A Data Set of Human
  Body Movements for Physical Rehabilitation Exercises.* Data 3(1):2,
  2018. UI-PRMD dataset home:
  `https://webpages.uidaho.edu/ui-prmd/`.
* MediaPipe Pose Landmarker documentation, Tasks Vision.
* COCO Keypoint Detection Task, `https://cocodataset.org/`.
* MMSkeleton reference implementation: `https://github.com/open-mmlab/mmskeleton`.
* Original ST-GCN implementation: `https://github.com/yysijie/st-gcn`.
* UI-PRMD Python port used as an ingestion reference:
  `https://github.com/tejas1904/UI-PRMD-Visualize-python-port`.

---

## 12. Open Questions

Items that need a decision before Phase 5 kicks off. None of them
block Phases 0-4.

1. **Which sensor stream from UI-PRMD?** Kinect is closer to what
   MediaPipe produces at runtime; Vicon is more accurate. Recommend:
   train on Kinect (matches deployment noise), evaluate on both and
   report the delta.
2. **Sequence length `T`?** UI-PRMD reps are ~2-6 s at 30 Hz.
   Recommend `T=64` with uniform resampling; revisit if the model
   struggles on the slowest movements (side lunge, shoulder scaption).
3. **Regression vs classification?** UI-PRMD ships a continuous
   quality score in addition to the binary label. Binary is simpler
   and matches the deployed coach vocabulary; the continuous score
   is a stretch goal for Phase 6+.
4. **Where to host the ONNX file?** GitHub Releases is the cheapest
   option; a signed S3 URL is more robust for later versioning. Defer
   to when the artefact exists.
