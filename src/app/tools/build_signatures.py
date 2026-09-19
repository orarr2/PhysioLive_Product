"""Build angle signatures from reference exercise videos.

Runs the pose backend against every mp4 under
`data/reference_videos/<exercise>/`, detects reps with the same state
machine the live pipeline uses, and writes one JSON signature per video
under `data/reference_signatures/<exercise>/`.

Each signature carries:

    {
      "exercise": "squat",
      "source_file": "squat_00.mp4",
      "fps": 30.0,
      "frame_count": 745,
      "reps": [
        {
          "index": 1,
          "duration_s": 3.2,
          "eccentric_s": 1.6,
          "concentric_s": 1.3,
          "hold_s": 0.3,
          "knee_min_deg": 92.4,
          "knee_max_deg": 172.1,
          "rom_deg": 79.7,
          "torso_max_deg": 33.5,
          "knee_over_toe_max_norm": 0.28,
          "primary_side": "left"
        }
      ],
      "summary": {
        "rep_count": 8,
        "knee_min_p50": 94.1,
        "knee_min_p90": 92.4,
        "rom_median_deg": 78.6,
        "tempo_ecc_median_s": 1.6,
        "tempo_con_median_s": 1.3
      }
    }

The summary is what the live pipeline compares each rep against - the
median target is a reasonable "correct" reference, while p90 flags the
lower bound of the range seen in the demonstration set.

Usage:
    python -m app.tools.build_signatures                     # all exercises
    python -m app.tools.build_signatures --exercise squat    # single
    python -m app.tools.build_signatures --frame-stride 2    # process every
                                                             # second frame
                                                             # for speed
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_ROOT / "src"))

from app.angles import all_angles                        # noqa: E402
from app.pose_gate import PoseInferencer                 # noqa: E402
from app.rep_counter import RepCounter                   # noqa: E402


VIDEOS_ROOT = _ROOT / "data" / "reference_videos"
SIGS_ROOT = _ROOT / "data" / "reference_signatures"

EXERCISE_CONFIGS = _ROOT / "src" / "app" / "exercises"


def _load_exercise(name: str) -> Dict:
    path = EXERCISE_CONFIGS / f"{name}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _median(vals: List[float]) -> Optional[float]:
    xs = [v for v in vals if v is not None]
    if not xs:
        return None
    return float(statistics.median(xs))


def _percentile(vals: List[float], p: float) -> Optional[float]:
    xs = sorted(v for v in vals if v is not None)
    if not xs:
        return None
    k = max(0, min(len(xs) - 1, int(round(p * (len(xs) - 1)))))
    return float(xs[k])


def process_video(path: Path, exercise: Dict,
                  pose: PoseInferencer,
                  frame_stride: int = 1) -> Dict:
    import cv2
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise RuntimeError(f"cannot open {path}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)

    rep_def = exercise["rep_definition"]
    primary_name = rep_def["primary_angle"]
    secondary_name = rep_def.get("secondary_angle")
    counter = RepCounter(
        standing_deg=rep_def["standing_deg"],
        bottom_deg=rep_def["bottom_deg"],
        hysteresis_deg=rep_def["hysteresis_deg"],
        confirm_frames=rep_def["confirm_frames"],
    )

    rep_records: List[Dict] = []
    # Tempo phase tracking: track when the rep started (last time we were
    # in STANDING), when the primary angle reached its minimum (turnaround),
    # and when the rep closed.
    rep_start_frame: Optional[int] = None
    rep_min_frame: Optional[int] = None
    rep_min_val: Optional[float] = None

    frame_idx = 0
    processed = 0
    read_ok = True
    while read_ok:
        read_ok, frame = cap.read()
        if not read_ok:
            break
        if frame_stride > 1 and (frame_idx % frame_stride) != 0:
            frame_idx += 1
            continue
        result = pose.infer(frame)
        kps = result.coco17 if result else None
        angles = all_angles(kps) if kps else {}
        primary_val = _pick_primary(angles, primary_name, secondary_name,
                                    counter.decreasing)
        metrics = _metrics_for(angles, counter.decreasing)

        pre_state = counter.state
        event = counter.update(primary_val, metrics=metrics)

        # Rep start: when the state machine flips STANDING -> BOTTOM.
        if pre_state == "STANDING" and counter.state == "BOTTOM":
            rep_start_frame = frame_idx
            rep_min_frame = frame_idx
            rep_min_val = primary_val
        # Track the turnaround point (deepest primary angle inside the rep).
        elif counter.state == "BOTTOM" and primary_val is not None:
            if rep_min_val is None:
                rep_min_val = primary_val
                rep_min_frame = frame_idx
            elif counter.decreasing and primary_val < rep_min_val:
                rep_min_val = primary_val
                rep_min_frame = frame_idx
            elif not counter.decreasing and primary_val > rep_min_val:
                rep_min_val = primary_val
                rep_min_frame = frame_idx

        if event is not None:
            start = rep_start_frame if rep_start_frame is not None else frame_idx
            turnaround = rep_min_frame if rep_min_frame is not None else frame_idx
            dur_frames = frame_idx - start
            ecc_dur = (turnaround - start) / max(1.0, fps)
            con_dur = (frame_idx - turnaround) / max(1.0, fps)
            rep_records.append({
                "index": event.index,
                "duration_s": round(dur_frames / max(1.0, fps), 2),
                "eccentric_s": round(max(0.0, ecc_dur), 2),
                "concentric_s": round(max(0.0, con_dur), 2),
                "hold_s": 0.0,
                "knee_min_deg": _num(event.sample.get_min("knee")
                                     or event.sample.get_min("primary")),
                "knee_max_deg": _num(event.sample.get_max("knee")
                                     or event.sample.get_max("primary")),
                "rom_deg": _rom(event.sample),
                "torso_max_deg": _num(
                    event.sample.get_max("torso_vertical")),
                "knee_over_toe_max_norm": _num(
                    event.sample.get_max("knee_over_toe_norm")),
                "frames": event.sample.frames,
            })
            rep_start_frame = None
            rep_min_frame = None
            rep_min_val = None
        frame_idx += 1
        processed += 1

    cap.release()

    knee_mins = [r["knee_min_deg"] for r in rep_records]
    roms = [r["rom_deg"] for r in rep_records]
    eccs = [r["eccentric_s"] for r in rep_records]
    cons = [r["concentric_s"] for r in rep_records]

    return {
        "exercise": exercise["id"],
        "source_file": path.name,
        "fps": round(fps, 2),
        "frame_count": total_frames,
        "processed_frames": processed,
        "frame_stride": frame_stride,
        "reps": rep_records,
        "summary": {
            "rep_count": len(rep_records),
            "knee_min_p10": _percentile(knee_mins, 0.10),
            "knee_min_p50": _median(knee_mins),
            "knee_min_p90": _percentile(knee_mins, 0.90),
            "rom_median_deg": _median(roms),
            "tempo_ecc_median_s": _median(eccs),
            "tempo_con_median_s": _median(cons),
        },
    }


def _num(v) -> Optional[float]:
    return None if v is None else round(float(v), 2)


def _rom(sample) -> Optional[float]:
    lo = sample.get_min("primary")
    hi = sample.get_max("primary")
    if lo is None or hi is None:
        return None
    return round(abs(hi - lo), 2)


def _pick_primary(angles, primary_name, secondary_name, decreasing):
    a = angles.get(primary_name)
    b = angles.get(secondary_name) if secondary_name else None
    if a is not None and b is not None:
        if decreasing:
            return a if a <= b else b
        return a if a >= b else b
    return a if a is not None else b


def _metrics_for(angles, decreasing):
    out = {}
    for name in ("knee_left", "knee_right"):
        v = angles.get(name)
        if v is None:
            continue
        prev = out.get("knee")
        out["knee"] = v if prev is None else min(prev, v)
    for name in ("hip_left", "hip_right"):
        v = angles.get(name)
        if v is None:
            continue
        prev = out.get("hip")
        if prev is None:
            out["hip"] = v
        else:
            out["hip"] = min(prev, v) if decreasing else max(prev, v)
    if angles.get("torso_vertical") is not None:
        out["torso_vertical"] = angles["torso_vertical"]
    torso_len = angles.get("torso_length")
    for side in ("left", "right"):
        kt = angles.get(f"knee_over_toe_{side}")
        if kt is not None and torso_len:
            norm = kt / torso_len
            prev = out.get("knee_over_toe_norm")
            out["knee_over_toe_norm"] = norm if prev is None else max(prev,
                                                                     norm)
    return out


def _is_at_bottom(primary_val, rep_def, decreasing):
    hyst = float(rep_def.get("hysteresis_deg", 8.0))
    if decreasing:
        return primary_val < (rep_def["bottom_deg"] + hyst)
    return primary_val > (rep_def["bottom_deg"] - hyst)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--exercise", type=str, default=None,
                    help="only build signatures for this exercise id")
    ap.add_argument("--frame-stride", type=int, default=1,
                    help="process every Nth frame (2 or 3 speeds up the "
                         "build with a small precision cost)")
    ap.add_argument("--backend", type=str, default="auto",
                    choices=["auto", "yolo", "mediapipe_pose",
                             "mediapipe_holistic"],
                    help="override the pose backend for signature building")
    args = ap.parse_args()

    if not VIDEOS_ROOT.exists():
        print(f"no videos root at {VIDEOS_ROOT}")
        return

    exercises = _discover_exercises(args.exercise)
    if not exercises:
        print("no exercises found with videos to process")
        return

    for ex_id in exercises:
        try:
            exercise = _load_exercise(ex_id)
        except Exception as e:
            print(f"skip {ex_id}: {e}")
            continue
        if args.backend != "auto":
            backend = args.backend
        else:
            backend = exercise.get("pose_backend", "mediapipe_holistic")
            # Signatures do not need finger detail; drop to the pose-only
            # backend for a big speedup.
            if backend == "mediapipe_holistic":
                backend = "mediapipe_pose"
        print(f"exercise {ex_id!r} backend={backend}")
        try:
            pose = PoseInferencer(backend=backend)
        except Exception as e:
            if backend != "yolo":
                print(f"  {backend} unavailable ({e}); falling back to yolo")
                backend = "yolo"
                pose = PoseInferencer(backend=backend)
            else:
                raise
        out_dir = SIGS_ROOT / ex_id
        out_dir.mkdir(parents=True, exist_ok=True)

        for mp4 in sorted((VIDEOS_ROOT / ex_id).glob("*.mp4")):
            t0 = time.perf_counter()
            print(f"  processing {mp4.name}...", flush=True)
            try:
                sig = process_video(mp4, exercise, pose,
                                    frame_stride=args.frame_stride)
            except Exception as e:
                print(f"    error: {type(e).__name__}: {e}")
                continue
            out_path = out_dir / f"{mp4.stem}.json"
            out_path.write_text(json.dumps(sig, indent=2), encoding="utf-8")
            dt = time.perf_counter() - t0
            s = sig["summary"]
            print(f"    -> {out_path.name}  reps={s['rep_count']} "
                  f"knee_min_p50={s['knee_min_p50']}  "
                  f"tempo ecc/con {s['tempo_ecc_median_s']}/"
                  f"{s['tempo_con_median_s']}s  ({dt:.1f}s)")


def _discover_exercises(only: Optional[str]) -> List[str]:
    if only:
        return [only] if (VIDEOS_ROOT / only).is_dir() else []
    return sorted(p.name for p in VIDEOS_ROOT.iterdir()
                  if p.is_dir() and any(p.glob("*.mp4")))


if __name__ == "__main__":
    main()
