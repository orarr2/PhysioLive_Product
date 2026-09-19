"""Deterministic form-check rules.

Each rule is a dict with an `id`, a `level` ('good'|'warn'|'bad'), messages
in Hebrew and English, and a `condition` block. Conditions supported by
the M2 evaluator:

- `rom_below`: rep's `knee_min_deg` did not go below `target_max_deg`.
- `knee_over_toe_side`: rep's `knee_over_toe_max_norm` exceeded threshold
  (positive = knee past ankle in image-x).
- `torso_vertical_gt`: rep's `torso_vertical_max_deg` exceeded threshold.

Rules run against a `RepSample` produced by `rep_counter.RepCounter`. The
evaluator returns a list of violations plus one summary verdict that the
UI colors and the voice worker speaks.
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
    message_he: str
    message_en: str


@dataclass
class Verdict:
    level: str
    text_he: str
    text_en: str
    violations: List[Violation]


def _eval_condition(cond: dict, sample: RepSample) -> bool:
    kind = cond.get("kind")
    if kind == "rom_below":
        km = sample.knee_min_deg
        if km is None:
            return False
        return km > float(cond.get("target_max_deg", 115))
    if kind == "knee_over_toe_side":
        kt = sample.knee_over_toe_max_norm
        if kt is None:
            return False
        return kt > float(cond.get("threshold_norm", 0.35))
    if kind == "torso_vertical_gt":
        tv = sample.torso_vertical_max_deg
        if tv is None:
            return False
        return tv > float(cond.get("threshold_deg", 45))
    return False


def evaluate(sample: RepSample, rules: List[dict],
             language: str = "he") -> Verdict:
    violations: List[Violation] = []
    for r in rules:
        cond = r.get("condition") or {}
        if _eval_condition(cond, sample):
            violations.append(Violation(
                rule_id=r["id"],
                level=r.get("level", "warn"),
                message_he=r.get("message_he", ""),
                message_en=r.get("message_en", ""),
            ))
    if not violations:
        return Verdict(level="good",
                       text_he="חזרה טובה. כל הכבוד.",
                       text_en="Good rep. Well done.",
                       violations=[])
    violations.sort(key=lambda v: LEVEL_ORDER.get(v.level, 0), reverse=True)
    top = violations[0]
    return Verdict(level=top.level,
                   text_he=top.message_he,
                   text_en=top.message_en,
                   violations=violations)
