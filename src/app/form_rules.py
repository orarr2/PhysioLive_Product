"""Deterministic form-check rules.

Each rule is a dict with an `id`, a `level` ('good' | 'warn' | 'bad'), a
`message` string, and a `condition` block. Supported condition kinds:

- `rom_below`: primary angle never went past a target minimum
  (`target_max_deg`). Used for shallow-squat / shallow-lunge checks.
- `knee_over_toe_side`: rep's `knee_over_toe_norm` max exceeded
  `threshold_norm` (positive = knee past ankle in image-x).
- `torso_vertical_gt`: rep's torso-vertical max exceeded
  `threshold_deg`.
- `hip_extension_below`: rep's `hip` max (largest hip angle reached)
  did not reach `target_deg`. Used for shallow glute bridge.
- `hip_extension_above`: rep's `hip` max exceeded `target_deg`. Used
  for over-arch detection.
- `hip_flexion_below`: rep's `hip` did not drop below `target_deg`
  (smaller hip angle = more flexion). Used for straight-leg raise.
- `knee_flexion_gt`: rep's `knee` min was below `180 - threshold_deg`
  (i.e. the knee bent more than allowed). Used for keep-the-leg-straight
  checks.
- `elbow_flexion_gt`: rep's `elbow` min was below `180 - threshold_deg`.
  Used for keep-the-arm-straight checks.
- `shoulder_abduction_below`: rep's `shoulder` max did not reach
  `target_deg`. Used for insufficient arm-raise range.

Rules run against a `RepSample` from `rep_counter.RepCounter`. The
evaluator returns a `Verdict` (level and message) plus the full list of
violations, worst level first.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from .rep_counter import RepSample


LEVEL_ORDER = {"good": 0, "warn": 1, "bad": 2}


@dataclass
class Violation:
    rule_id: str
    level: str
    message: str


@dataclass
class Verdict:
    level: str
    text: str
    violations: List[Violation]


def _eval_condition(cond: dict, sample: RepSample) -> bool:
    kind = cond.get("kind")
    if kind == "rom_below":
        v = sample.get_min("primary")
        if v is None:
            return False
        return v > float(cond.get("target_max_deg", 115))
    if kind == "knee_over_toe_side":
        v = sample.get_max("knee_over_toe_norm")
        if v is None:
            return False
        return v > float(cond.get("threshold_norm", 0.35))
    if kind == "torso_vertical_gt":
        v = sample.get_max("torso_vertical")
        if v is None:
            return False
        return v > float(cond.get("threshold_deg", 45))
    if kind == "hip_extension_below":
        v = sample.get_max("hip")
        if v is None:
            v = sample.get_max("primary")
        if v is None:
            return False
        return v < float(cond.get("target_deg", 160))
    if kind == "hip_extension_above":
        v = sample.get_max("hip")
        if v is None:
            v = sample.get_max("primary")
        if v is None:
            return False
        return v > float(cond.get("target_deg", 185))
    if kind == "hip_flexion_below":
        v = sample.get_min("hip")
        if v is None:
            v = sample.get_min("primary")
        if v is None:
            return False
        return v > float(cond.get("target_deg", 120))
    if kind == "knee_flexion_gt":
        v = sample.get_min("knee")
        if v is None:
            return False
        threshold = 180.0 - float(cond.get("threshold_deg", 20))
        return v < threshold
    if kind == "elbow_flexion_gt":
        v = sample.get_min("elbow")
        if v is None:
            return False
        threshold = 180.0 - float(cond.get("threshold_deg", 35))
        return v < threshold
    if kind == "shoulder_abduction_below":
        v = sample.get_max("shoulder")
        if v is None:
            v = sample.get_max("primary")
        if v is None:
            return False
        return v < float(cond.get("target_deg", 80))
    return False


def evaluate(sample: RepSample, rules: List[dict]) -> Verdict:
    violations: List[Violation] = []
    for r in rules:
        cond = r.get("condition") or {}
        if _eval_condition(cond, sample):
            violations.append(Violation(
                rule_id=r["id"],
                level=r.get("level", "warn"),
                message=r.get("message", ""),
            ))
    if not violations:
        return Verdict(level="good",
                       text="Good rep. Nicely done.",
                       violations=[])
    violations.sort(key=lambda v: LEVEL_ORDER.get(v.level, 0), reverse=True)
    top = violations[0]
    return Verdict(level=top.level, text=top.message, violations=violations)
