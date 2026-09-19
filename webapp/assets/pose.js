/**
 * Pose backend using MediaPipe Tasks Vision for the browser.
 *
 * Downloads `pose_landmarker_full.task` (~7 MB) from Google's public
 * model bucket on first use. The Wasm runtime is fetched from the
 * unpkg CDN. Everything runs client-side; no video ever leaves the
 * browser.
 */

const WASM_PATH =
  "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.14/wasm";
const MODEL_URL =
  "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_full/float16/1/pose_landmarker_full.task";

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

let _landmarker = null;
let _initPromise = null;

export async function ensurePose() {
  if (_landmarker) return _landmarker;
  if (_initPromise) return _initPromise;
  _initPromise = (async () => {
    const vision = await import(
      "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.14/vision_bundle.mjs");
    const fileset = await vision.FilesetResolver.forVisionTasks(WASM_PATH);
    _landmarker = await vision.PoseLandmarker.createFromOptions(fileset, {
      baseOptions: { modelAssetPath: MODEL_URL },
      runningMode: "VIDEO",
      numPoses: 1,
      minPoseDetectionConfidence: 0.5,
      minPosePresenceConfidence: 0.5,
      minTrackingConfidence: 0.5,
    });
    return _landmarker;
  })();
  return _initPromise;
}

export async function inferPose(video, ts) {
  const landmarker = await ensurePose();
  if (video.readyState < 2) return null;
  const result = landmarker.detectForVideo(video, ts);
  if (!result || !result.landmarks || result.landmarks.length === 0) {
    return null;
  }
  return result.landmarks[0];
}

/**
 * Draw a colored skeleton over the video onto the canvas 2D context.
 */
export function drawSkeleton(ctx, landmarks, width, height,
                             minVisibility = 0.4) {
  if (!landmarks) return;
  // Halo pass for readability, then colored pass.
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
  // Neck: mid-shoulder to nose.
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
  // Joints.
  for (const lm of landmarks) {
    if (!_vis(lm, minVisibility)) continue;
    ctx.fillStyle = "rgba(240,240,240,0.9)";
    ctx.beginPath();
    ctx.arc(lm.x * width, lm.y * height, 4, 0, Math.PI * 2);
    ctx.fill();
  }
}

function _vis(lm, min) {
  if (!lm) return false;
  const v = lm.visibility != null ? lm.visibility : 1;
  return v >= min;
}
