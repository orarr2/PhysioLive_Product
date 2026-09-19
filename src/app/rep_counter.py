"""Repetition counter.

Runs a simple state machine on the primary angle:

    STANDING  --(angle < bottom_deg + hyst for confirm_frames)-->  BOTTOM
    BOTTOM    --(angle > standing_deg - hyst for confirm_frames)--> STANDING (+1 rep)

`confirm_frames` is a two-tick confirmation: a single-frame dip does not
count as a rep, and a single-frame spike does not close one.

While the rep is active, the counter tracks the rep's angle min and max
so downstream rules (rom_below, knee_over_toe max within rep, torso lean
max within rep) can be evaluated at rep-end.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class RepSample:
    knee_min_deg: Optional[float] = None
    knee_max_deg: Optional[float] = None
    torso_vertical_max_deg: Optional[float] = None
    knee_over_toe_max_norm: Optional[float] = None
    frames: int = 0


@dataclass
class RepEvent:
    index: int
    sample: RepSample


class RepCounter:

    def __init__(self, standing_deg: float = 170.0, bottom_deg: float = 100.0,
                 hysteresis_deg: float = 8.0,
                 confirm_frames: int = 2) -> None:
        self.standing_deg = float(standing_deg)
        self.bottom_deg = float(bottom_deg)
        self.hysteresis_deg = float(hysteresis_deg)
        self.confirm_frames = int(confirm_frames)
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

    def update(self, knee_angle: Optional[float],
               torso_vertical: Optional[float] = None,
               knee_over_toe_norm: Optional[float] = None
               ) -> Optional[RepEvent]:
        """Feed one frame's readings; returns a RepEvent when a rep closes."""
        self.last_event = None
        if knee_angle is None:
            return None

        if self.state == "STANDING":
            self._up_hits = 0
            if knee_angle < (self.bottom_deg + self.hysteresis_deg):
                self._down_hits += 1
                if self._down_hits >= self.confirm_frames:
                    self.state = "BOTTOM"
                    self._current = RepSample()
                    self._track(knee_angle, torso_vertical,
                                knee_over_toe_norm)
            else:
                self._down_hits = 0
        else:
            self._down_hits = 0
            self._track(knee_angle, torso_vertical, knee_over_toe_norm)
            if knee_angle > (self.standing_deg - self.hysteresis_deg):
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

    def _track(self, knee_angle: float,
               torso_vertical: Optional[float],
               knee_over_toe_norm: Optional[float]) -> None:
        s = self._current
        if s is None:
            return
        s.frames += 1
        if s.knee_min_deg is None or knee_angle < s.knee_min_deg:
            s.knee_min_deg = knee_angle
        if s.knee_max_deg is None or knee_angle > s.knee_max_deg:
            s.knee_max_deg = knee_angle
        if torso_vertical is not None:
            if (s.torso_vertical_max_deg is None
                    or torso_vertical > s.torso_vertical_max_deg):
                s.torso_vertical_max_deg = torso_vertical
        if knee_over_toe_norm is not None:
            if (s.knee_over_toe_max_norm is None
                    or knee_over_toe_norm > s.knee_over_toe_max_norm):
                s.knee_over_toe_max_norm = knee_over_toe_norm
