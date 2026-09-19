"""Joint-angle math on top of the canonical 17-point layout.

All angles are in degrees. Every function returns `None` when any
required keypoint is below `min_conf`, so callers never see a fabricated
verdict.

Input is a flat list of 17 `[x, y, conf]` triples in COCO order. If you
have a `PoseFrame` from `pose_gate.PoseInferencer`, pass its `.coco17`.
"""
from __future__ import annotations

import math
from typing import Optional

from .pose_gate import (
    KP_MIN_CONF, L_ANKLE, L_ELBOW, L_HIP, L_KNEE, L_SHOULDER, L_WRIST,
    R_ANKLE, R_ELBOW, R_HIP, R_KNEE, R_SHOULDER, R_WRIST,
)


def _pt(kps, idx, min_conf):
    x, y, c = kps[idx]
    if c < min_conf:
        return None
    return (float(x), float(y))


def _angle3(a, b, c) -> float:
    """Angle at `b` formed by `a-b-c`, in degrees. `b` is the vertex."""
    ax, ay = a
    bx, by = b
    cx, cy = c
    v1x, v1y = ax - bx, ay - by
    v2x, v2y = cx - bx, cy - by
    dot = v1x * v2x + v1y * v2y
    n1 = math.hypot(v1x, v1y) or 1e-9
    n2 = math.hypot(v2x, v2y) or 1e-9
    cos = max(-1.0, min(1.0, dot / (n1 * n2)))
    return math.degrees(math.acos(cos))


def knee_angle(kps, side: str, min_conf: float = KP_MIN_CONF) -> Optional[float]:
    """Hip-knee-ankle angle. `side` is 'left' or 'right'."""
    if side == "left":
        hip, knee, ankle = L_HIP, L_KNEE, L_ANKLE
    else:
        hip, knee, ankle = R_HIP, R_KNEE, R_ANKLE
    a = _pt(kps, hip, min_conf)
    b = _pt(kps, knee, min_conf)
    c = _pt(kps, ankle, min_conf)
    if not (a and b and c):
        return None
    return _angle3(a, b, c)


def hip_angle(kps, side: str, min_conf: float = KP_MIN_CONF) -> Optional[float]:
    """Shoulder-hip-knee angle."""
    if side == "left":
        sh, hip, knee = L_SHOULDER, L_HIP, L_KNEE
    else:
        sh, hip, knee = R_SHOULDER, R_HIP, R_KNEE
    a = _pt(kps, sh, min_conf)
    b = _pt(kps, hip, min_conf)
    c = _pt(kps, knee, min_conf)
    if not (a and b and c):
        return None
    return _angle3(a, b, c)


def elbow_angle(kps, side: str, min_conf: float = KP_MIN_CONF) -> Optional[float]:
    if side == "left":
        sh, el, wr = L_SHOULDER, L_ELBOW, L_WRIST
    else:
        sh, el, wr = R_SHOULDER, R_ELBOW, R_WRIST
    a = _pt(kps, sh, min_conf)
    b = _pt(kps, el, min_conf)
    c = _pt(kps, wr, min_conf)
    if not (a and b and c):
        return None
    return _angle3(a, b, c)


def torso_vertical_angle(kps, min_conf: float = KP_MIN_CONF) -> Optional[float]:
    """Angle between the shoulder-hip axis and the vertical (0 = upright)."""
    l_sh = _pt(kps, L_SHOULDER, min_conf)
    r_sh = _pt(kps, R_SHOULDER, min_conf)
    l_hp = _pt(kps, L_HIP, min_conf)
    r_hp = _pt(kps, R_HIP, min_conf)
    shs = [p for p in (l_sh, r_sh) if p]
    hps = [p for p in (l_hp, r_hp) if p]
    if not shs or not hps:
        return None
    sh = (sum(p[0] for p in shs) / len(shs),
          sum(p[1] for p in shs) / len(shs))
    hp = (sum(p[0] for p in hps) / len(hps),
          sum(p[1] for p in hps) / len(hps))
    dx, dy = hp[0] - sh[0], hp[1] - sh[1]
    return math.degrees(math.atan2(abs(dx), abs(dy) or 1e-6))


def knee_over_toe_offset(kps, side: str,
                         min_conf: float = KP_MIN_CONF) -> Optional[float]:
    """Signed horizontal offset (pixels) of the knee past the ankle.

    Positive = knee is forward of the ankle in image-x, which is the
    "knee over toe" position when the user is filmed from the side.
    Returns None when either joint is not confidently seen.
    """
    if side == "left":
        knee_i, ankle_i = L_KNEE, L_ANKLE
    else:
        knee_i, ankle_i = R_KNEE, R_ANKLE
    knee = _pt(kps, knee_i, min_conf)
    ankle = _pt(kps, ankle_i, min_conf)
    if not (knee and ankle):
        return None
    return knee[0] - ankle[0]


def torso_length(kps, min_conf: float = KP_MIN_CONF) -> Optional[float]:
    """Shoulder-mid to hip-mid Euclidean distance. Used to normalise
    pixel offsets across users and camera distances."""
    l_sh = _pt(kps, L_SHOULDER, min_conf)
    r_sh = _pt(kps, R_SHOULDER, min_conf)
    l_hp = _pt(kps, L_HIP, min_conf)
    r_hp = _pt(kps, R_HIP, min_conf)
    shs = [p for p in (l_sh, r_sh) if p]
    hps = [p for p in (l_hp, r_hp) if p]
    if not shs or not hps:
        return None
    sh = (sum(p[0] for p in shs) / len(shs),
          sum(p[1] for p in shs) / len(shs))
    hp = (sum(p[0] for p in hps) / len(hps),
          sum(p[1] for p in hps) / len(hps))
    return math.hypot(hp[0] - sh[0], hp[1] - sh[1]) or None


def all_angles(kps, min_conf: float = KP_MIN_CONF) -> dict:
    """Compute every angle used by the rules engine in one pass."""
    return {
        "knee_left": knee_angle(kps, "left", min_conf),
        "knee_right": knee_angle(kps, "right", min_conf),
        "hip_left": hip_angle(kps, "left", min_conf),
        "hip_right": hip_angle(kps, "right", min_conf),
        "torso_vertical": torso_vertical_angle(kps, min_conf),
        "knee_over_toe_left": knee_over_toe_offset(kps, "left", min_conf),
        "knee_over_toe_right": knee_over_toe_offset(kps, "right", min_conf),
        "torso_length": torso_length(kps, min_conf),
    }
