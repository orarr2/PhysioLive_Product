/**
 * State-machine rep counter, direction-agnostic. Mirrors
 * `src/app/rep_counter.py`.
 */

export class RepSample {
  constructor() {
    this.metrics = {};
    this.frames = 0;
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
  constructor({ standingDeg, bottomDeg, hysteresisDeg = 8, confirmFrames = 2 }) {
    this.standingDeg = standingDeg;
    this.bottomDeg = bottomDeg;
    this.hysteresisDeg = hysteresisDeg;
    this.confirmFrames = confirmFrames;
    this.decreasing = bottomDeg < standingDeg;
    this.state = "STANDING";
    this.count = 0;
    this._downHits = 0;
    this._upHits = 0;
    this._current = null;
  }

  reset() {
    this.state = "STANDING";
    this.count = 0;
    this._downHits = 0;
    this._upHits = 0;
    this._current = null;
  }

  _towardBottom(a) {
    if (this.decreasing) return a < (this.bottomDeg + this.hysteresisDeg);
    return a > (this.bottomDeg - this.hysteresisDeg);
  }
  _towardStanding(a) {
    if (this.decreasing) return a > (this.standingDeg - this.hysteresisDeg);
    return a < (this.standingDeg + this.hysteresisDeg);
  }

  update(primaryAngle, metrics = {}) {
    if (primaryAngle == null) return null;
    if (this.state === "STANDING") {
      this._upHits = 0;
      if (this._towardBottom(primaryAngle)) {
        this._downHits++;
        if (this._downHits >= this.confirmFrames) {
          this.state = "BOTTOM";
          this._current = new RepSample();
          this._track(primaryAngle, metrics);
        }
      } else {
        this._downHits = 0;
      }
    } else {
      this._downHits = 0;
      this._track(primaryAngle, metrics);
      if (this._towardStanding(primaryAngle)) {
        this._upHits++;
        if (this._upHits >= this.confirmFrames) {
          this.state = "STANDING";
          this.count++;
          const sample = this._current;
          this._current = null;
          this._upHits = 0;
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
