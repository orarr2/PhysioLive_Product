"""Repetition counter.

Runs a simple state machine on the primary joint angle:

    STANDING  --(angle crosses the bottom threshold for confirm_frames)-->  BOTTOM
    BOTTOM    --(angle crosses the standing threshold for confirm_frames)--> STANDING (+1 rep)

The counter accepts either direction of motion. In a squat the knee
angle decreases from ~170 (standing) to ~100 (bottom); in a shoulder
abduction the shoulder angle increases from 5 (arm down) to 85 (arm
raised). The counter infers the direction from whether `bottom_deg` is
less than or greater than `standing_deg`.

`confirm_frames` is a two-tick confirmation: a single-frame dip does not
count as a rep, and a single-frame spike does not close one.

The counter also tracks per-rep min and max of every metric the caller
passes to `update()` so downstream rules can score the finished rep.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional


@dataclass
class RepSample:
    """Per-rep min / max for every metric the caller tracked."""

    metrics: Dict[str, Dict[str, float]] = field(default_factory=dict)
    frames: int = 0

    def get_min(self, name: str) -> Optional[float]:
        m = self.metrics.get(name)
        return None if m is None else m.get("min")

    def get_max(self, name: str) -> Optional[float]:
        m = self.metrics.get(name)
        return None if m is None else m.get("max")

    # Backwards-compat convenience for the original squat rules.
    @property
    def knee_min_deg(self) -> Optional[float]:
        return self.get_min("knee_primary") or self.get_min("knee_left") \
            or self.get_min("knee_right")

    @property
    def knee_max_deg(self) -> Optional[float]:
        return self.get_max("knee_primary") or self.get_max("knee_left") \
            or self.get_max("knee_right")

    @property
    def torso_vertical_max_deg(self) -> Optional[float]:
        return self.get_max("torso_vertical")

    @property
    def knee_over_toe_max_norm(self) -> Optional[float]:
        return self.get_max("knee_over_toe_norm")


@dataclass
class RepEvent:
    index: int
    sample: RepSample


class RepCounter:

    def __init__(self, standing_deg: float, bottom_deg: float,
                 hysteresis_deg: float = 8.0,
                 confirm_frames: int = 2) -> None:
        self.standing_deg = float(standing_deg)
        self.bottom_deg = float(bottom_deg)
        self.hysteresis_deg = float(hysteresis_deg)
        self.confirm_frames = int(confirm_frames)
        # Decreasing: knee squats down. Increasing: arm raises up.
        self.decreasing = self.bottom_deg < self.standing_deg
        self.state = "STANDING"
        self.count = 0
        self._down_hits = 0
        self._up_hits = 0
        self._current: Optional[RepSample] = None
        self.last_event: Optional[RepEvent] = None

    def reset(self) -> None:
        self.state = "STANDING"
        self.count = 0
        self._down_hits = 0
        self._up_hits = 0
        self._current = None
        self.last_event = None

    def update(self, primary_angle: Optional[float],
               metrics: Optional[Dict[str, Optional[float]]] = None
               ) -> Optional[RepEvent]:
        """Feed one frame; returns a RepEvent when a rep closes.

        `metrics` is a mapping name -> current value. Every non-None
        metric is min / max tracked for the duration of the rep so rules
        can score at rep-end. `primary_angle` also gets tracked under the
        name `primary`.
        """
        self.last_event = None
        if primary_angle is None:
            return None

        crossed_toward_bottom = self._is_toward_bottom(primary_angle)
        crossed_toward_standing = self._is_toward_standing(primary_angle)

        if self.state == "STANDING":
            self._up_hits = 0
            if crossed_toward_bottom:
                self._down_hits += 1
                if self._down_hits >= self.confirm_frames:
                    self.state = "BOTTOM"
                    self._current = RepSample()
                    self._track(primary_angle, metrics)
            else:
                self._down_hits = 0
        else:
            self._down_hits = 0
            self._track(primary_angle, metrics)
            if crossed_toward_standing:
                self._up_hits += 1
                if self._up_hits >= self.confirm_frames:
                    self.state = "STANDING"
                    self.count += 1
                    sample = self._current or RepSample()
                    self._current = None
                    self._up_hits = 0
                    self.last_event = RepEvent(index=self.count,
                                               sample=sample)
                    return self.last_event
            else:
                self._up_hits = 0
        return None

    def _is_toward_bottom(self, angle: float) -> bool:
        if self.decreasing:
            return angle < (self.bottom_deg + self.hysteresis_deg)
        return angle > (self.bottom_deg - self.hysteresis_deg)

    def _is_toward_standing(self, angle: float) -> bool:
        if self.decreasing:
            return angle > (self.standing_deg - self.hysteresis_deg)
        return angle < (self.standing_deg + self.hysteresis_deg)

    def _track(self, primary_angle: float,
               metrics: Optional[Dict[str, Optional[float]]]) -> None:
        s = self._current
        if s is None:
            return
        s.frames += 1
        self._update_metric(s, "primary", primary_angle)
        if not metrics:
            return
        for name, value in metrics.items():
            if value is not None:
                self._update_metric(s, name, float(value))

    def _update_metric(self, sample: RepSample, name: str,
                       value: float) -> None:
        m = sample.metrics.get(name)
        if m is None:
            sample.metrics[name] = {"min": value, "max": value}
        else:
            if value < m["min"]:
                m["min"] = value
            if value > m["max"]:
                m["max"] = value
