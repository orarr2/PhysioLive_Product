/**
 * State-machine rep counter, direction-agnostic. Mirrors
 * `src/app/rep_counter.py`.
 *
 * Adjustments over the desktop version:
 *   - Brief null frames (up to `maxNullFrames`) are tolerated instead
 *     of resetting hit counters. A quick visibility drop mid-rep no
 *     longer wipes progress.
 *   - `shallowDeg` (optional) lets a rep count when the primary angle
 *     reaches somewhere between the shallow and full-depth threshold.
 *     The sample is flagged `shallow: true` so the rule engine can
 *     issue a "shallow rep" verdict instead of the rep vanishing.
 */

export class RepSample {
  constructor() {
    this.metrics = {};
    this.frames = 0;
    this.shallow = false;
  }
  getMin(name) {
    const m = this.metrics[name];
    return m ? m.min : null;
  }
  getMax(name) {
    const m = this.metrics[name];
    return m ? m.max : null;
  }
  _track(name, v) {
    if (v == null) return;
    const m = this.metrics[name];
    if (!m) this.metrics[name] = { min: v, max: v };
    else {
      if (v < m.min) m.min = v;
      if (v > m.max) m.max = v;
    }
  }
}

export class RepCounter {
  constructor({ standingDeg, bottomDeg, hysteresisDeg = 8, confirmFrames = 2,
                shallowDeg = null, maxNullFrames = 5 }) {
    this.standingDeg = standingDeg;
    this.bottomDeg = bottomDeg;
    this.shallowDeg = shallowDeg;
    this.hysteresisDeg = hysteresisDeg;
    this.confirmFrames = confirmFrames;
    this.maxNullFrames = maxNullFrames;
    this.decreasing = bottomDeg < standingDeg;
    this.state = "STANDING";
    this.count = 0;
    this._downHits = 0;
    this._upHits = 0;
    this._current = null;
    this._nullStreak = 0;
    this._reachedFullDepth = false;
  }

  reset() {
    this.state = "STANDING";
    this.count = 0;
    this._downHits = 0;
    this._upHits = 0;
    this._current = null;
    this._nullStreak = 0;
    this._reachedFullDepth = false;
  }

  get displayPhase() {
    if (this.state === "STANDING" && this._downHits > 0) return "DESCENDING";
    if (this.state === "BOTTOM" && this._upHits > 0) return "RISING";
    return this.state;
  }

  _towardBottom(a) {
    if (this.decreasing) return a < (this.bottomDeg + this.hysteresisDeg);
    return a > (this.bottomDeg - this.hysteresisDeg);
  }
  _towardShallow(a) {
    if (this.shallowDeg == null) return this._towardBottom(a);
    if (this.decreasing) return a < (this.shallowDeg + this.hysteresisDeg);
    return a > (this.shallowDeg - this.hysteresisDeg);
  }
  _towardStanding(a) {
    if (this.decreasing) return a > (this.standingDeg - this.hysteresisDeg);
    return a < (this.standingDeg + this.hysteresisDeg);
  }

  update(primaryAngle, metrics = {}) {
    if (primaryAngle == null) {
      this._nullStreak++;
      if (this._nullStreak <= this.maxNullFrames) {
        // Tolerate a brief visibility gap without wiping progress.
        return null;
      }
      // Extended blackout - reset the hit accumulators but stay in
      // whichever high-level state we are in. The rep count itself is
      // never reset until the user explicitly starts a new session.
      this._downHits = 0;
      this._upHits = 0;
      return null;
    }
    this._nullStreak = 0;

    if (this.state === "STANDING") {
      this._upHits = 0;
      // Enter descent whenever the angle is at or past the shallow
      // target - we can promote to full-depth further down without
      // ever losing the rep.
      if (this._towardShallow(primaryAngle)) {
        this._downHits++;
        if (this._downHits >= this.confirmFrames) {
          this.state = "BOTTOM";
          this._current = new RepSample();
          this._reachedFullDepth = this._towardBottom(primaryAngle);
          this._track(primaryAngle, metrics);
        }
      } else {
        this._downHits = 0;
      }
    } else {
      this._downHits = 0;
      this._track(primaryAngle, metrics);
      if (this._towardBottom(primaryAngle)) {
        this._reachedFullDepth = true;
      }
      if (this._towardStanding(primaryAngle)) {
        this._upHits++;
        if (this._upHits >= this.confirmFrames) {
          this.state = "STANDING";
          this.count++;
          const sample = this._current;
          if (sample) sample.shallow = !this._reachedFullDepth;
          this._current = null;
          this._upHits = 0;
          this._reachedFullDepth = false;
          return { index: this.count, sample };
        }
      } else {
        this._upHits = 0;
      }
    }
    return null;
  }

  _track(primaryAngle, metrics) {
    const s = this._current;
    if (!s) return;
    s.frames++;
    s._track("primary", primaryAngle);
    for (const [k, v] of Object.entries(metrics || {})) {
      if (v != null) s._track(k, v);
    }
  }
}
