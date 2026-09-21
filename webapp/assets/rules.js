/**
 * Deterministic form rules - the JavaScript port of `src/app/form_rules.py`.
 * Every condition kind supported by the Python evaluator is implemented
 * here so the same exercise config drives both platforms.
 */

const LEVEL_ORDER = { good: 0, warn: 1, bad: 2 };

function evalCondition(cond, sample) {
  const kind = cond.kind;
  if (kind === "rom_below") {
    const v = sample.getMin("primary");
    if (v == null) return false;
    return v > (cond.targetMaxDeg ?? 115);
  }
  if (kind === "knee_over_toe_side") {
    const v = sample.getMax("knee_over_toe_norm");
    if (v == null) return false;
    return v > (cond.thresholdNorm ?? 0.35);
  }
  if (kind === "torso_vertical_gt") {
    const v = sample.getMax("torso_vertical");
    if (v == null) return false;
    return v > (cond.thresholdDeg ?? 45);
  }
  if (kind === "hip_extension_below") {
    const v = sample.getMax("hip") ?? sample.getMax("primary");
    if (v == null) return false;
    return v < (cond.targetDeg ?? 160);
  }
  if (kind === "hip_extension_above") {
    const v = sample.getMax("hip") ?? sample.getMax("primary");
    if (v == null) return false;
    return v > (cond.targetDeg ?? 185);
  }
  if (kind === "hip_flexion_below") {
    const v = sample.getMin("hip") ?? sample.getMin("primary");
    if (v == null) return false;
    return v > (cond.targetDeg ?? 120);
  }
  if (kind === "knee_flexion_gt") {
    const v = sample.getMin("knee");
    if (v == null) return false;
    return v < (180 - (cond.thresholdDeg ?? 20));
  }
  if (kind === "elbow_flexion_gt") {
    const v = sample.getMin("elbow");
    if (v == null) return false;
    return v < (180 - (cond.thresholdDeg ?? 35));
  }
  if (kind === "shoulder_abduction_below") {
    const v = sample.getMax("shoulder") ?? sample.getMax("primary");
    if (v == null) return false;
    return v < (cond.targetDeg ?? 80);
  }
  return false;
}

export function evaluate(sample, rules) {
  const violations = [];
  // A shallow rep that would otherwise pass every rule still deserves
  // feedback so the user knows to go deeper next time.
  if (sample && sample.shallow) {
    violations.push({
      ruleId: "shallow_soft", level: "warn",
      message: "Rep counted, but shallow. Try to reach the target depth.",
    });
  }
  for (const r of rules) {
    if (evalCondition(r.condition || {}, sample)) {
      violations.push({
        ruleId: r.id, level: r.level || "warn",
        message: r.message || "",
      });
    }
  }
  if (!violations.length) {
    return { level: "good", text: "Good rep. Nicely done.", violations };
  }
  violations.sort((a, b) => (LEVEL_ORDER[b.level] || 0)
                             - (LEVEL_ORDER[a.level] || 0));
  const top = violations[0];
  return { level: top.level, text: top.message, violations };
}
