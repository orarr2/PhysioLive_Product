/**
 * Exercise configuration - kept in sync with src/app/exercises/*.json.
 * Each entry drives the state machine and the form rules for one exercise.
 */

export const EXERCISES = {
  squat: {
    id: "squat",
    name: "Squat",
    repGoal: 12,
    repDef: {
      primary: "knee",
      standingDeg: 170,
      bottomDeg: 100,
      // A rep whose primary angle reaches at least shallowDeg (but
      // never bottomDeg) still counts, tagged as shallow so the user
      // sees feedback instead of silence.
      shallowDeg: 130,
      hysteresisDeg: 8,
      confirmFrames: 2,
      // Squat is bilateral: both knees must satisfy the descent test
      // together, so a single-leg raise no longer counts as a rep.
      bilateral: true,
    },
    rules: [
      {
        id: "shallow_depth",
        level: "warn",
        message: "Shallow rep. Try to go deeper within your range.",
        condition: { kind: "rom_below", targetMaxDeg: 115 },
      },
      {
        id: "knee_over_toe",
        level: "warn",
        message: "Knee is past the toe. Keep the knee over the ankle.",
        condition: { kind: "knee_over_toe_side", thresholdNorm: 0.35 },
      },
      {
        id: "torso_lean",
        level: "warn",
        message: "Torso leaning too far forward. Engage the core and stay upright.",
        condition: { kind: "torso_vertical_gt", thresholdDeg: 45 },
      },
    ],
  },
  lunge: {
    id: "lunge",
    name: "Forward Lunge",
    repGoal: 10,
    repDef: {
      primary: "knee",
      standingDeg: 170,
      bottomDeg: 95,
      hysteresisDeg: 8,
      confirmFrames: 2,
    },
    rules: [
      {
        id: "shallow_depth",
        level: "warn",
        message: "Front knee did not reach 90 degrees. Sink deeper if the range is comfortable.",
        condition: { kind: "rom_below", targetMaxDeg: 100 },
      },
      {
        id: "torso_lean",
        level: "warn",
        message: "Torso leaning forward. Keep the chest tall and hinge at the hip.",
        condition: { kind: "torso_vertical_gt", thresholdDeg: 35 },
      },
    ],
  },
  glute_bridge: {
    id: "glute_bridge",
    name: "Glute Bridge",
    repGoal: 12,
    repDef: {
      primary: "hip",
      standingDeg: 165,
      bottomDeg: 110,
      shallowDeg: 130,
      hysteresisDeg: 6,
      confirmFrames: 2,
      bilateral: true,
    },
    rules: [
      {
        id: "shallow_bridge",
        level: "warn",
        message: "Hip lift is shallow. Drive the hips higher.",
        condition: { kind: "hip_extension_below", targetDeg: 160 },
      },
    ],
  },
  leg_raise: {
    id: "leg_raise",
    name: "Straight Leg Raise",
    repGoal: 12,
    repDef: {
      primary: "hip",
      standingDeg: 170,
      bottomDeg: 110,
      hysteresisDeg: 6,
      confirmFrames: 2,
    },
    rules: [
      {
        id: "insufficient_lift",
        level: "warn",
        message: "Leg did not lift high enough.",
        condition: { kind: "hip_flexion_below", targetDeg: 120 },
      },
    ],
  },
  shoulder_abduction: {
    id: "shoulder_abduction",
    name: "Shoulder Abduction",
    repGoal: 15,
    repDef: {
      primary: "shoulder",
      standingDeg: 5,
      bottomDeg: 85,
      hysteresisDeg: 6,
      confirmFrames: 2,
    },
    rules: [
      {
        id: "insufficient_range",
        level: "warn",
        message: "Arm did not reach shoulder height.",
        condition: { kind: "shoulder_abduction_below", targetDeg: 80 },
      },
    ],
  },
};
