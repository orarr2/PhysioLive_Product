"""Per-user calibration.

Rehabilitation targets should be defined relative to the patient's own
range of motion, not absolute joint angles. This module runs a short
warm-up capture where the user does one slow repetition; the observed
minimum and maximum primary-angle values become the personalised
`bottom_deg` and `standing_deg` thresholds passed into the rep counter.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Optional

import numpy as np

from .angles import all_angles
from .pose_gate import PoseInferencer


@dataclass
class Calibration:
    exercise: str
    primary_family: str
    standing_deg: float
    bottom_deg: float
    hysteresis_deg: float
    samples: int


def _pick_primary(angles: dict, family: str) -> Optional[float]:
    if family == "knee":
        left = angles.get("knee_left")
        right = angles.get("knee_right")
    elif family == "hip":
        left = angles.get("hip_left")
        right = angles.get("hip_right")
    elif family == "shoulder":
        left = angles.get("shoulder_left")
        right = angles.get("shoulder_right")
    elif family == "elbow":
        left = angles.get("elbow_left")
        right = angles.get("elbow_right")
    else:
        return None
    if left is not None and right is not None:
        return min(left, right)
    return left if left is not None else right


def calibrate(cap, pose: PoseInferencer, family: str, exercise: str,
              duration_s: float = 6.0,
              on_frame: Optional[Callable] = None) -> Calibration:
    """Sample primary angle for `duration_s` seconds. Returns thresholds.

    `on_frame(elapsed, primary_val)` is called after every processed
    frame so a caller can drive a UI (progress bar, HUD tint).
    """
    values = []
    t0 = time.perf_counter()
    while True:
        elapsed = time.perf_counter() - t0
        if elapsed >= duration_s:
            break
        ok, frame = cap.read()
        if not ok:
            continue
        result = pose.infer(frame)
        primary_val = None
        if result is not None:
            angles = all_angles(result.coco17)
            primary_val = _pick_primary(angles, family)
            if primary_val is not None:
                values.append(primary_val)
        if on_frame is not None:
            try:
                on_frame(elapsed, primary_val)
            except Exception:
                pass

    if len(values) < 10:
        raise RuntimeError(
            "not enough clean pose frames during calibration - check "
            "camera framing and lighting, then try again")

    arr = np.asarray(values, dtype="float32")
    p5 = float(np.percentile(arr, 5))
    p95 = float(np.percentile(arr, 95))
    # Personalised range with a small margin so the state machine has
    # room to work.
    hysteresis = max(4.0, min(12.0, (p95 - p5) * 0.05))
    return Calibration(
        exercise=exercise,
        primary_family=family,
        standing_deg=round(p95, 1),
        bottom_deg=round(p5, 1),
        hysteresis_deg=round(hysteresis, 1),
        samples=len(values),
    )
