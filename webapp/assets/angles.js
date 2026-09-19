/**
 * Angle math on top of MediaPipe's 33-landmark layout. Mirrors the
 * `src/app/angles.py` behaviour: every function returns null when any
 * required landmark is below the visibility gate.
 */

import { MP } from "./pose.js";

const MIN_VIS = 0.4;

function pt(lm, idx) {
  const p = lm[idx];
  if (!p) return null;
  const v = p.visibility != null ? p.visibility : 1;
  if (v < MIN_VIS) return null;
  return { x: p.x, y: p.y };
}

function angle3(a, b, c) {
  const v1x = a.x - b.x, v1y = a.y - b.y;
  const v2x = c.x - b.x, v2y = c.y - b.y;
  const dot = v1x * v2x + v1y * v2y;
  const n1 = Math.hypot(v1x, v1y) || 1e-9;
  const n2 = Math.hypot(v2x, v2y) || 1e-9;
  const cos = Math.max(-1, Math.min(1, dot / (n1 * n2)));
  return Math.acos(cos) * 180 / Math.PI;
}

export function kneeAngle(lm, side) {
  const [hip, knee, ankle] = side === "left"
    ? [MP.L_HIP, MP.L_KNEE, MP.L_ANKLE]
    : [MP.R_HIP, MP.R_KNEE, MP.R_ANKLE];
  const a = pt(lm, hip), b = pt(lm, knee), c = pt(lm, ankle);
  if (!a || !b || !c) return null;
  return angle3(a, b, c);
}

export function hipAngle(lm, side) {
  const [sh, hip, knee] = side === "left"
    ? [MP.L_SHOULDER, MP.L_HIP, MP.L_KNEE]
    : [MP.R_SHOULDER, MP.R_HIP, MP.R_KNEE];
  const a = pt(lm, sh), b = pt(lm, hip), c = pt(lm, knee);
  if (!a || !b || !c) return null;
  return angle3(a, b, c);
}

export function elbowAngle(lm, side) {
  const [sh, el, wr] = side === "left"
    ? [MP.L_SHOULDER, MP.L_ELBOW, MP.L_WRIST]
    : [MP.R_SHOULDER, MP.R_ELBOW, MP.R_WRIST];
  const a = pt(lm, sh), b = pt(lm, el), c = pt(lm, wr);
  if (!a || !b || !c) return null;
  return angle3(a, b, c);
}

export function shoulderAbductionAngle(lm, side) {
  const [sh, el, hip] = side === "left"
    ? [MP.L_SHOULDER, MP.L_ELBOW, MP.L_HIP]
    : [MP.R_SHOULDER, MP.R_ELBOW, MP.R_HIP];
  const shPt = pt(lm, sh), elPt = pt(lm, el), hipPt = pt(lm, hip);
  if (!shPt || !elPt || !hipPt) return null;
  return angle3(hipPt, shPt, elPt);
}

export function torsoVerticalAngle(lm) {
  const l_sh = pt(lm, MP.L_SHOULDER), r_sh = pt(lm, MP.R_SHOULDER);
  const l_hp = pt(lm, MP.L_HIP), r_hp = pt(lm, MP.R_HIP);
  const shs = [l_sh, r_sh].filter(Boolean);
  const hps = [l_hp, r_hp].filter(Boolean);
  if (!shs.length || !hps.length) return null;
  const sh = { x: shs.reduce((s, p) => s + p.x, 0) / shs.length,
               y: shs.reduce((s, p) => s + p.y, 0) / shs.length };
  const hp = { x: hps.reduce((s, p) => s + p.x, 0) / hps.length,
               y: hps.reduce((s, p) => s + p.y, 0) / hps.length };
  const dx = hp.x - sh.x, dy = hp.y - sh.y;
  return Math.atan2(Math.abs(dx), Math.abs(dy) || 1e-6) * 180 / Math.PI;
}

export function torsoLength(lm) {
  const l_sh = pt(lm, MP.L_SHOULDER), r_sh = pt(lm, MP.R_SHOULDER);
  const l_hp = pt(lm, MP.L_HIP), r_hp = pt(lm, MP.R_HIP);
  const shs = [l_sh, r_sh].filter(Boolean);
  const hps = [l_hp, r_hp].filter(Boolean);
  if (!shs.length || !hps.length) return null;
  const sh = { x: shs.reduce((s, p) => s + p.x, 0) / shs.length,
               y: shs.reduce((s, p) => s + p.y, 0) / shs.length };
  const hp = { x: hps.reduce((s, p) => s + p.x, 0) / hps.length,
               y: hps.reduce((s, p) => s + p.y, 0) / hps.length };
  return Math.hypot(hp.x - sh.x, hp.y - sh.y) || null;
}

export function kneeOverToeOffset(lm, side) {
  const [knee, ankle] = side === "left"
    ? [MP.L_KNEE, MP.L_ANKLE]
    : [MP.R_KNEE, MP.R_ANKLE];
  const k = pt(lm, knee), a = pt(lm, ankle);
  if (!k || !a) return null;
  return k.x - a.x;
}

export function allAngles(lm) {
  return {
    knee_left: kneeAngle(lm, "left"),
    knee_right: kneeAngle(lm, "right"),
    hip_left: hipAngle(lm, "left"),
    hip_right: hipAngle(lm, "right"),
    elbow_left: elbowAngle(lm, "left"),
    elbow_right: elbowAngle(lm, "right"),
    shoulder_left: shoulderAbductionAngle(lm, "left"),
    shoulder_right: shoulderAbductionAngle(lm, "right"),
    torso_vertical: torsoVerticalAngle(lm),
    knee_over_toe_left: kneeOverToeOffset(lm, "left"),
    knee_over_toe_right: kneeOverToeOffset(lm, "right"),
    torso_length: torsoLength(lm),
  };
}
