/**
 * Pose + hand backends using MediaPipe Tasks Vision for the browser.
 *
 * The browser build of Tasks Vision does not (yet) ship a
 * HolisticLandmarker, so we run two models in parallel:
 *
 *   - PoseLandmarker (`pose_landmarker_full.task`, ~7 MB)  - 33 body
 *     landmarks. Drives rep counting and form rules.
 *   - HandLandmarker (`hand_landmarker.task`, ~5 MB)       - up to
 *     two hands, 21 joints per hand. Purely visual - draws finger
 *     skeletons onto the overlay so users see the same rich
 *     representation the desktop notebook produces.
 *
 * The Wasm runtime is fetched from the jsdelivr CDN. Everything runs
 * client-side; no video ever leaves the browser.
 */

const WASM_PATH =
  "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.14/wasm";
const POSE_MODEL_URL =
  "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_full/float16/1/pose_landmarker_full.task";
const HAND_MODEL_URL =
  "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task";

// MediaPipe pose landmark indices (33-landmark layout).
export const MP = {
  NOSE: 0,
  L_SHOULDER: 11, R_SHOULDER: 12,
  L_ELBOW: 13, R_ELBOW: 14,
  L_WRIST: 15, R_WRIST: 16,
  L_HIP: 23, R_HIP: 24,
  L_KNEE: 25, R_KNEE: 26,
  L_ANKLE: 27, R_ANKLE: 28,
};

// Bone groups by anatomy for color-coded rendering.
const BONE_GROUPS = [
  { color: "#ffd700", edges: [[0, 1], [1, 2], [2, 3], [3, 7], [0, 4],
                              [4, 5], [5, 6], [6, 8], [9, 10]] },
  { color: "#a842e8", edges: [[11, 12], [11, 23], [12, 24], [23, 24]] },
  { color: "#ffb400", edges: [[11, 13], [13, 15], [15, 17], [15, 19],
                              [15, 21], [17, 19]] },
  { color: "#50dc50", edges: [[12, 14], [14, 16], [16, 18], [16, 20],
                              [16, 22], [18, 20]] },
  { color: "#ffff00", edges: [[23, 25], [25, 27], [27, 29], [29, 31],
                              [27, 31]] },
  { color: "#ff6438", edges: [[24, 26], [26, 28], [28, 30], [30, 32],
                              [28, 32]] },
];

// 21-joint hand skeleton (thumb, index, middle, ring, pinky, palm base).
const HAND_EDGES = [
  [0, 1], [1, 2], [2, 3], [3, 4],
  [0, 5], [5, 6], [6, 7], [7, 8],
  [5, 9], [9, 10], [10, 11], [11, 12],
  [9, 13], [13, 14], [14, 15], [15, 16],
  [13, 17], [17, 18], [18, 19], [19, 20],
  [0, 17],
];
const HAND_COLORS = { Left: "#22d3ee", Right: "#f472b6" };

let _pose = null;
let _hand = null;
let _initPromise = null;
let _handInitFailed = false;

export async function ensurePose() {
  if (_pose) return _pose;
  if (_initPromise) return _initPromise;
  _initPromise = (async () => {
    const vision = await import(
      "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.14/vision_bundle.mjs");
    const fileset = await vision.FilesetResolver.forVisionTasks(WASM_PATH);
    _pose = await vision.PoseLandmarker.createFromOptions(fileset, {
      baseOptions: { modelAssetPath: POSE_MODEL_URL },
      runningMode: "VIDEO",
      numPoses: 1,
      minPoseDetectionConfidence: 0.5,
      minPosePresenceConfidence: 0.5,
      minTrackingConfidence: 0.5,
    });
    // Hand model is best-effort; if it fails to load we just skip
    // finger rendering rather than block the whole live loop.
    try {
      _hand = await vision.HandLandmarker.createFromOptions(fileset, {
        baseOptions: { modelAssetPath: HAND_MODEL_URL },
        runningMode: "VIDEO",
        numHands: 2,
        minHandDetectionConfidence: 0.5,
        minHandPresenceConfidence: 0.5,
        minTrackingConfidence: 0.5,
      });
    } catch (e) {
      console.warn("HandLandmarker unavailable, skipping fingers:", e);
      _handInitFailed = true;
    }
    return _pose;
  })();
  return _initPromise;
}

/**
 * Run pose inference (always) and hand inference (when available).
 * Returns { pose, hands, handedness } where hands is [[21 joints], ...]
 * and handedness is parallel with each entry {label, score}.
 */
export async function inferPose(video, ts) {
  const pose = await ensurePose();
  if (video.readyState < 2) return null;
  const poseResult = pose.detectForVideo(video, ts);
  const body = (poseResult && poseResult.landmarks && poseResult.landmarks[0])
    || null;
  let hands = null, handedness = null;
  if (_hand && !_handInitFailed) {
    try {
      const hr = _hand.detectForVideo(video, ts);
      if (hr && hr.landmarks && hr.landmarks.length) {
        hands = hr.landmarks;
        handedness = (hr.handedness || []).map(h => h && h[0]
          ? { label: h[0].categoryName, score: h[0].score }
          : null);
      }
    } catch (e) {
      // Never break the pose loop over a hand failure.
      console.warn("hand inference error", e);
    }
  }
  if (!body && !hands) return null;
  return { pose: body, hands, handedness };
}

/**
 * Draw a colored body skeleton + finger skeletons onto the overlay
 * canvas 2D context.
 */
export function drawSkeleton(ctx, frame, width, height,
                             minVisibility = 0.4) {
  if (!frame) return;
  drawBody(ctx, frame.pose, width, height, minVisibility);
  if (frame.hands) drawHands(ctx, frame.hands, frame.handedness, width, height);
}

function drawBody(ctx, landmarks, width, height, minVisibility) {
  if (!landmarks) return;
  ctx.lineWidth = 5;
  ctx.strokeStyle = "rgba(20,20,20,0.9)";
  for (const group of BONE_GROUPS) {
    for (const [i, j] of group.edges) {
      const a = landmarks[i], b = landmarks[j];
      if (!_vis(a, minVisibility) || !_vis(b, minVisibility)) continue;
      ctx.beginPath();
      ctx.moveTo(a.x * width, a.y * height);
      ctx.lineTo(b.x * width, b.y * height);
      ctx.stroke();
    }
  }
  ctx.lineWidth = 3;
  for (const group of BONE_GROUPS) {
    ctx.strokeStyle = group.color;
    for (const [i, j] of group.edges) {
      const a = landmarks[i], b = landmarks[j];
      if (!_vis(a, minVisibility) || !_vis(b, minVisibility)) continue;
      ctx.beginPath();
      ctx.moveTo(a.x * width, a.y * height);
      ctx.lineTo(b.x * width, b.y * height);
      ctx.stroke();
    }
  }
  const ls = landmarks[MP.L_SHOULDER];
  const rs = landmarks[MP.R_SHOULDER];
  const nose = landmarks[MP.NOSE];
  if (_vis(ls, minVisibility) && _vis(rs, minVisibility)
      && _vis(nose, minVisibility)) {
    const mx = (ls.x + rs.x) / 2 * width;
    const my = (ls.y + rs.y) / 2 * height;
    ctx.strokeStyle = "#ffdcb4";
    ctx.beginPath();
    ctx.moveTo(mx, my);
    ctx.lineTo(nose.x * width, nose.y * height);
    ctx.stroke();
  }
  for (const lm of landmarks) {
    if (!_vis(lm, minVisibility)) continue;
    ctx.fillStyle = "rgba(240,240,240,0.9)";
    ctx.beginPath();
    ctx.arc(lm.x * width, lm.y * height, 4, 0, Math.PI * 2);
    ctx.fill();
  }
}

function drawHands(ctx, handsArr, handednessArr, width, height) {
  handsArr.forEach((hand, i) => {
    if (!hand) return;
    const label = handednessArr && handednessArr[i]
      ? handednessArr[i].label : "Right";
    const color = HAND_COLORS[label] || "#22d3ee";
    // Halo pass for readability.
    ctx.lineWidth = 4;
    ctx.strokeStyle = "rgba(20,20,20,0.9)";
    for (const [a, b] of HAND_EDGES) {
      const p = hand[a], q = hand[b];
      if (!p || !q) continue;
      ctx.beginPath();
      ctx.moveTo(p.x * width, p.y * height);
      ctx.lineTo(q.x * width, q.y * height);
      ctx.stroke();
    }
    ctx.lineWidth = 2.2;
    ctx.strokeStyle = color;
    for (const [a, b] of HAND_EDGES) {
      const p = hand[a], q = hand[b];
      if (!p || !q) continue;
      ctx.beginPath();
      ctx.moveTo(p.x * width, p.y * height);
      ctx.lineTo(q.x * width, q.y * height);
      ctx.stroke();
    }
    // Joint dots.
    for (const p of hand) {
      if (!p) continue;
      ctx.fillStyle = "rgba(255,255,255,0.9)";
      ctx.beginPath();
      ctx.arc(p.x * width, p.y * height, 2.6, 0, Math.PI * 2);
      ctx.fill();
    }
  });
}

function _vis(lm, min) {
  if (!lm) return false;
  const v = lm.visibility != null ? lm.visibility : 1;
  return v >= min;
}
