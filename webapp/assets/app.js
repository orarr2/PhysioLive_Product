/**
 * PhysioLive web app - entry point.
 *
 * Three view states (data-view on <body>):
 *   - landing:  exercise picker + hero
 *   - live:     camera + skeleton + HUD + feedback
 *   - summary:  end-of-session stats + rep table
 *
 * Access is gated by a sign-in modal (Google or passphrase). Only
 * signed-in users get a camera stream or reach the VM.
 */

import { EXERCISES } from "./exercises.js";
import { ensurePose, inferPose, drawSkeleton } from "./pose.js";
import { allAngles } from "./angles.js";
import { RepCounter } from "./rep_counter.js";
import { evaluate } from "./rules.js";
import { requestCoach } from "./coach_client.js";
import { resolveVmOrigin, CONFIG } from "./config.js";
import {
  currentUserId, getSavedProfile, isSignedIn, signOut,
  signInWithPassphrase, renderGoogleButton,
} from "./auth.js";
import {
  openSession, appendRep, closeSession, pastSessions,
} from "./session.js";
import { sendDailyReport } from "./report_client.js";

// ============================================================ STATE
const state = {
  exerciseId: "squat",
  view: "landing",
  running: false,
  video: null,
  canvas: null,
  ctx: null,
  stream: null,
  loopHandle: null,
  repCounter: null,
  sessionId: null,
  reps: [],
  stats: { good: 0, warn: 0, bad: 0 },
  startedAt: 0,
  timerHandle: null,
  lastCoachTs: 0,
  cameras: [],
  activeCameraId: null,
  activeFacing: "user",
  framingMissingFrames: 0,
  framingHintActive: false,
  camReadyEventFired: false,
  posesSeen: 0,
  handsSeen: 0,
  cameraOpenedAt: 0,
  debugAutoShown: false,
};

// Meta / icons for the exercise cards.
const EX_META = {
  squat:              { view: "Front camera", goal: "12 reps", icon: iconSquat() },
  lunge:              { view: "Side camera",  goal: "10 reps", icon: iconLunge() },
  glute_bridge:       { view: "Side camera",  goal: "12 reps", icon: iconBridge() },
  leg_raise:          { view: "Side camera",  goal: "12 reps", icon: iconLeg() },
  shoulder_abduction: { view: "Front camera", goal: "15 reps", icon: iconShoulder() },
};

const CAMERA_STORAGE_KEY = "physiolive.camera_device_id";

// ============================================================ BOOT
window.addEventListener("DOMContentLoaded", async () => {
  wireLanding();
  wireLive();
  wireSummary();
  wireHistoryDrawer();
  wireSignIn();
  wireNavSignIn();

  refreshSignInLabel();
  // Fire and forget - the tunnel-url.json fetch is used by every
  // request that follows, so we resolve it as soon as the DOM is up.
  resolveVmOrigin().catch(() => { /* silent - fallback handles it */ });
});

// ============================================================ VIEW HELPERS
function setView(view) {
  state.view = view;
  document.body.dataset.view = view;
  document.getElementById("view-landing").hidden = view !== "landing";
  document.getElementById("view-live").hidden = view !== "live";
  document.getElementById("view-summary").hidden = view !== "summary";
  window.scrollTo({ top: 0 });
}

function toast(msg, ms = 2500) {
  const t = document.getElementById("toast");
  t.textContent = msg;
  t.hidden = false;
  clearTimeout(toast._h);
  toast._h = setTimeout(() => { t.hidden = true; }, ms);
}

function refreshSignInLabel() {
  const label = document.getElementById("signin-label");
  if (!label) return;
  const profile = getSavedProfile();
  label.textContent = profile
    ? (profile.name || profile.display_name || profile.email || "You")
        .split(" ")[0]
    : "Sign in";
}

// ============================================================ LANDING
function wireLanding() {
  const grid = document.getElementById("exercise-grid");
  Object.values(EXERCISES).forEach(ex => {
    const meta = EX_META[ex.id] || { view: "-", goal: "-", icon: iconGeneric() };
    const el = document.createElement("button");
    el.className = "exercise-card";
    el.dataset.id = ex.id;
    el.innerHTML = `
      <div class="exercise-icon">${meta.icon}</div>
      <div class="exercise-name">${ex.name}</div>
      <div class="exercise-meta">
        <span>${meta.view}</span>
        <span>&middot;</span>
        <span>${meta.goal}</span>
      </div>
      <div class="exercise-cta">
        Start
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12h14"/><path d="M12 5l7 7-7 7"/></svg>
      </div>
    `;
    el.addEventListener("click", () => beginSession(ex.id));
    grid.appendChild(el);
  });

  document.getElementById("start-btn")
    .addEventListener("click", () => beginSession(state.exerciseId));
}

// ============================================================ LIVE
function wireLive() {
  state.video = document.getElementById("cam");
  state.canvas = document.getElementById("overlay");
  state.ctx = state.canvas.getContext("2d");

  document.getElementById("stop-btn").addEventListener("click", endSession);

  // Track dimensions -> match container aspect-ratio to the video.
  state.video.addEventListener("loadedmetadata", updateStageAspect);
  state.video.addEventListener("resize", updateStageAspect);

  // Camera picker. deviceId is kept in-session only (see openCameraStream
  // for why we never persist it).
  const sel = document.getElementById("camera-select");
  sel.addEventListener("change", async (e) => {
    const id = e.target.value;
    state.activeCameraId = id;
    await switchCamera(id);
  });

  // Diagnostics close button.
  const dbgClose = document.getElementById("cam-debug-close");
  if (dbgClose) dbgClose.addEventListener("click", () => {
    document.getElementById("cam-debug").hidden = true;
  });
}

// -------------------------------------------------------------- diagnostics
/**
 * Refresh the on-screen camera diagnostics panel. Auto-opens after
 * 3 s if the video has not started painting real frames yet, so the
 * user sees exactly which layer is failing without asking the dev
 * for another round of "please try again".
 */
let _dbgLastRender = 0;
function updateCameraDebug() {
  const now = Date.now();
  if (now - _dbgLastRender < 400) return;
  _dbgLastRender = now;

  const panel = document.getElementById("cam-debug");
  const rows = document.getElementById("cam-debug-rows");
  if (!panel || !rows) return;

  const v = state.video;
  const stream = state.stream;
  const tracks = stream ? stream.getVideoTracks() : [];
  const t = tracks[0];
  const settings = t && t.getSettings ? t.getSettings() : {};
  const elapsed = state.cameraOpenedAt
    ? ((now - state.cameraOpenedAt) / 1000).toFixed(1) + "s" : "-";

  const painted = v.videoWidth > 0 && v.videoHeight > 0;
  const shouldAutoShow =
    state.cameraOpenedAt
    && (now - state.cameraOpenedAt) > 3000
    && (!painted || v.paused || state.posesSeen === 0)
    && !state.debugAutoShown;
  if (shouldAutoShow) {
    panel.hidden = false;
    state.debugAutoShown = true;
  }
  if (panel.hidden) return;

  const items = [
    ["stream tracks", tracks.length, tracks.length >= 1 ? "ok" : "bad"],
    ["track state", t ? t.readyState : "-", t && t.readyState === "live" ? "ok" : "bad"],
    ["track muted", t ? String(t.muted) : "-", t && !t.muted ? "ok" : "bad"],
    ["track label", t ? (t.label || "-") : "-", ""],
    ["facingMode", settings.facingMode || state.activeFacing || "-", ""],
    ["v.readyState", v.readyState, v.readyState >= 2 ? "ok" : "bad"],
    ["v.paused", String(v.paused), v.paused ? "bad" : "ok"],
    ["v.dimensions", `${v.videoWidth}x${v.videoHeight}`, painted ? "ok" : "bad"],
    ["v.currentTime", v.currentTime.toFixed(2), v.currentTime > 0 ? "ok" : "bad"],
    ["playing event", state.camReadyEventFired ? "yes" : "no", state.camReadyEventFired ? "ok" : "bad"],
    ["poses detected", state.posesSeen, state.posesSeen > 0 ? "ok" : "bad"],
    ["hands detected", state.handsSeen, ""],
    ["elapsed", elapsed, ""],
    ["UA", (navigator.userAgent.match(/(iPhone|iPad|Android|Chrome|Safari|Firefox|Edg)\/?\S*/g) || []).slice(0, 3).join(" "), ""],
  ];
  rows.innerHTML = "";
  items.forEach(([k, val, cls]) => {
    const row = document.createElement("div");
    row.className = "cam-debug-row";
    row.innerHTML = `<span class="cam-debug-row-key"></span><span class="cam-debug-row-val ${cls || ""}"></span>`;
    row.children[0].textContent = k;
    row.children[1].textContent = String(val);
    rows.appendChild(row);
  });
}

function describeCameraError(e) {
  const name = (e && e.name) || "";
  if (name === "NotAllowedError" || name === "SecurityError") {
    return "Camera access was blocked. Grant permission in your "
         + "browser settings and reload the page.";
  }
  if (name === "NotFoundError" || name === "OverconstrainedError") {
    return "No usable camera was found. If you are on iOS, try the "
         + "back camera or close other apps using the camera.";
  }
  if (name === "NotReadableError") {
    return "The camera is busy in another app. Close FaceTime, Zoom, "
         + "or other browsers and try again.";
  }
  return `Camera error: ${(e && e.message) || e}`;
}

function updateStageAspect() {
  const stage = document.querySelector(".live-stage");
  const v = state.video;
  if (!stage || !v || !v.videoWidth || !v.videoHeight) return;
  const isPortraitMobile =
    window.matchMedia("(max-width: 640px) and (orientation: portrait)").matches;
  if (isPortraitMobile) {
    // On portrait phones the CSS media query handles the height, so
    // we skip the ratio override - it would fight the fixed height.
    return;
  }
  stage.style.aspectRatio = `${v.videoWidth} / ${v.videoHeight}`;
}

async function ensureAuthedOrPrompt() {
  if (isSignedIn()) return true;
  openSignInModal();
  return false;
}

async function beginSession(exerciseId) {
  if (!await ensureAuthedOrPrompt()) return;

  state.exerciseId = exerciseId;
  const ex = EXERCISES[exerciseId];
  if (!ex) return;

  setView("live");
  document.getElementById("live-exercise-name").textContent = ex.name;
  document.getElementById("hud-angle-label").textContent =
    primaryLabel(ex.repDef.primary) + " angle";
  document.getElementById("hud-goal").textContent = ex.repGoal;
  document.getElementById("hud-reps").textContent = "0";
  document.getElementById("hud-phase").textContent = "STANDING";
  document.getElementById("hud-angle").textContent = "--";
  document.getElementById("feedback-log").innerHTML =
    '<div class="feedback-empty">Coach messages will show up here.</div>';
  document.getElementById("feedback-count").textContent = "0";
  updateMini({ good: 0, warn: 0, elapsed: 0 });
  setCoach("Camera is starting. Stand back so your full body is in frame.",
           "idle", null);
  updateRing(0, ex.repGoal, "");

  showLoading(true);
  try {
    // Never persist deviceId across page loads - iOS Safari changes
    // deviceIds between grants and a stale id yields a black stream.
    await openCameraStream(state.activeCameraId);
    await ensurePose();
    await refreshCameraList();
  } catch (e) {
    showLoading(false);
    const msg = describeCameraError(e);
    setCoach(msg, "bad", null);
    return;
  }
  showLoading(false);
  state.framingMissingFrames = 0;
  state.framingHintActive = false;
  state.posesSeen = 0;
  state.handsSeen = 0;
  state.debugAutoShown = false;
  document.getElementById("cam-debug").hidden = true;

  state.repCounter = new RepCounter(ex.repDef);
  state.reps = [];
  state.stats = { good: 0, warn: 0, bad: 0 };
  state.startedAt = Date.now();
  const uid = currentUserId() || "u_anon";
  state.sessionId = openSession(uid, exerciseId);
  state.running = true;

  state.timerHandle = setInterval(() => {
    updateMini({
      good: state.stats.good,
      warn: state.stats.warn,
      elapsed: Math.round((Date.now() - state.startedAt) / 1000),
    });
  }, 1000);

  setCoach("Great. Start when you are ready.", "idle", null);
  loop();
}

function showLoading(v) {
  document.getElementById("live-loading").hidden = !v;
}

// -------------------------------------------------------------- camera
/**
 * Open a camera stream. iOS Safari refuses `{deviceId: {exact}}` when
 * the device isn't yet known (no prior permission grant) and it also
 * fails hard on `OverconstrainedError` without falling back. We walk
 * an explicit ladder of constraints so the first successful one wins.
 *
 * Order:
 *   1. exact deviceId  (only after a prior grant this session).
 *   2. facingMode user (front / selfie).
 *   3. facingMode env  (back camera on phones).
 *   4. video: true     (whatever the browser gives us).
 */
async function openCameraStream(preferredDeviceId) {
  if (state.stream) {
    state.stream.getTracks().forEach(t => t.stop());
    state.stream = null;
  }
  // Do NOT null out srcObject on iOS - transitioning from null back to
  // a stream is a known trigger for the black-video state. We only
  // clear it if there is nothing to replace it with.

  const attempts = [];
  if (preferredDeviceId) {
    attempts.push({
      video: {
        deviceId: { exact: preferredDeviceId },
        width: { ideal: 1280 }, height: { ideal: 720 },
      },
      audio: false,
    });
  }
  attempts.push({
    video: {
      facingMode: { ideal: "user" },
      width: { ideal: 1280 }, height: { ideal: 720 },
    },
    audio: false,
  });
  attempts.push({
    video: {
      facingMode: { ideal: "environment" },
      width: { ideal: 1280 }, height: { ideal: 720 },
    },
    audio: false,
  });
  attempts.push({ video: true, audio: false });

  let stream = null;
  let lastError = null;
  for (const constraints of attempts) {
    try {
      stream = await navigator.mediaDevices.getUserMedia(constraints);
      if (stream && stream.getVideoTracks().length) break;
    } catch (e) {
      lastError = e;
      // Overconstrained / NotFound / NotReadable -> try next rung.
    }
  }
  if (!stream) {
    throw lastError || new Error("Could not open any camera");
  }

  // iOS Safari: playsinline + muted must be present on the element
  // BEFORE the stream is attached, otherwise the first playback attempt
  // silently produces black frames. We set them again defensively.
  state.video.muted = true;
  state.video.setAttribute("playsinline", "");
  state.video.setAttribute("webkit-playsinline", "true");
  state.video.setAttribute("autoplay", "");

  state.stream = stream;
  state.video.srcObject = stream;

  // Kick playback. On iOS the first play() can reject if the media
  // pipeline is still warming up; we wait for `loadedmetadata` and
  // retry. If the video is still zero-sized 800ms after play resolves
  // we call load() once - this is the specific incantation that
  // recovers from iOS Safari's black-video state after a stream swap.
  const kickPlay = async () => {
    try { await state.video.play(); } catch (_) { /* handled below */ }
  };
  await kickPlay();
  if (state.video.readyState < 2) {
    await new Promise((resolve) => {
      const on = () => {
        state.video.removeEventListener("loadedmetadata", on);
        resolve();
      };
      state.video.addEventListener("loadedmetadata", on, { once: true });
      setTimeout(on, 1500);
    });
    await kickPlay();
  }
  // Force a re-render pass if iOS handed us a black surface.
  await new Promise(r => setTimeout(r, 800));
  if (!state.video.videoWidth || state.video.paused) {
    try { state.video.load(); } catch (_) { /* noop */ }
    await kickPlay();
  }

  const track = stream.getVideoTracks()[0];
  if (track) {
    const settings = track.getSettings ? track.getSettings() : {};
    state.activeCameraId = settings.deviceId || preferredDeviceId || null;
    state.activeFacing = settings.facingMode || guessFacing(track.label);
    document.querySelector(".live-stage")
      .setAttribute("data-facing", state.activeFacing || "user");
  }
  state.cameraOpenedAt = Date.now();
  state.camReadyEventFired = false;
  const onReady = () => {
    state.camReadyEventFired = true;
    state.video.removeEventListener("playing", onReady);
    state.video.removeEventListener("loadeddata", onReady);
  };
  state.video.addEventListener("playing", onReady);
  state.video.addEventListener("loadeddata", onReady);
  updateStageAspect();
}

function guessFacing(label) {
  const s = (label || "").toLowerCase();
  if (s.includes("back") || s.includes("rear") || s.includes("environment")) {
    return "environment";
  }
  return "user";
}

async function refreshCameraList() {
  try {
    const devices = await navigator.mediaDevices.enumerateDevices();
    const cams = devices.filter(d => d.kind === "videoinput");
    state.cameras = cams;
    const sel = document.getElementById("camera-select");
    const wrap = document.getElementById("camera-select-wrap");
    sel.innerHTML = "";
    cams.forEach((cam, i) => {
      const opt = document.createElement("option");
      opt.value = cam.deviceId;
      opt.textContent = cam.label || `Camera ${i + 1}`;
      if (cam.deviceId === state.activeCameraId) opt.selected = true;
      sel.appendChild(opt);
    });
    wrap.hidden = cams.length < 2;
  } catch (e) {
    console.warn("enumerateDevices failed", e);
  }
}

async function switchCamera(deviceId) {
  showLoading(true);
  try {
    await openCameraStream(deviceId);
  } catch (e) {
    setCoach(describeCameraError(e), "bad", null);
  }
  showLoading(false);
}

/**
 * Show a hint when the exercise's required lower-body landmarks are
 * out of frame for more than ~2 seconds. Reset the hint once they
 * come back so the coach message returns to whatever it was showing.
 * MediaPipe reports each landmark's `visibility` in [0, 1]; below ~0.5
 * the joint is either occluded or off-frame.
 */
const FRAMING_JOINTS = [23, 24, 25, 26, 27, 28]; // hips, knees, ankles
const FRAMING_MIN_VISIBILITY = 0.5;
const FRAMING_FRAMES_TO_HINT = 45;   // roughly 2 seconds at 20 fps

function checkFraming(pose) {
  if (!pose) return;
  const missing = FRAMING_JOINTS.some(idx => {
    const lm = pose[idx];
    if (!lm) return true;
    const v = lm.visibility != null ? lm.visibility : 1;
    return v < FRAMING_MIN_VISIBILITY;
  });
  if (missing) {
    state.framingMissingFrames++;
    if (state.framingMissingFrames >= FRAMING_FRAMES_TO_HINT
        && !state.framingHintActive) {
      state.framingHintActive = true;
      setCoach(
        "Step back so your hips, knees and ankles are all in the "
        + "frame. Reps only count when the whole body is visible.",
        "warn", null);
    }
  } else {
    if (state.framingHintActive) {
      state.framingHintActive = false;
      setCoach("Nice - full body in frame. Start when you are ready.",
               "idle", null);
    }
    state.framingMissingFrames = 0;
  }
}

// -------------------------------------------------------------- loop
async function loop() {
  if (!state.running) return;
  const ts = performance.now();
  const frame = await inferPose(state.video, ts);
  const w = state.video.videoWidth || state.canvas.width || 1280;
  const h = state.video.videoHeight || state.canvas.height || 720;
  if (state.canvas.width !== w) state.canvas.width = w;
  if (state.canvas.height !== h) state.canvas.height = h;
  state.ctx.clearRect(0, 0, w, h);
  if (frame) drawSkeleton(state.ctx, frame, w, h);
  if (frame && frame.pose) state.posesSeen++;
  if (frame && frame.hands) state.handsSeen += frame.hands.length;
  updateCameraDebug();

  const lm = frame && frame.pose;
  if (!lm) {
    // No pose at all - either the camera is not delivering frames yet
    // or the user is fully out of frame. Reset the framing hint after
    // ~3 s of nothing so a stale message doesn't hide a real problem.
    state.framingMissingFrames++;
    if (state.framingMissingFrames > 60 && state.framingHintActive) {
      state.framingHintActive = false;
      setCoach("Waiting for a full body in the frame. Stand back so "
             + "your head, hips and ankles are all visible.",
               "warn", null);
    }
  }
  if (lm) {
    checkFraming(lm);
    const ex = EXERCISES[state.exerciseId];
    const angles = allAngles(lm);
    const primary = pickPrimary(angles, ex);
    const metrics = buildMetrics(angles, ex.repDef.bottomDeg < ex.repDef.standingDeg);
    const event = state.repCounter.update(primary, metrics);
    document.getElementById("hud-phase").textContent = state.repCounter.displayPhase;
    document.getElementById("hud-angle").textContent =
      primary != null ? `${Math.round(primary)}°` : "--";
    // Live during-rep indicators: depth %, form flash on mid-rep
    // form breaks. All observable BEFORE rep-close so the user can
    // course-correct instead of only reading feedback after.
    updateDepthIndicator(primary, ex);
    updateFormFlash(metrics, ex);

    if (event) {
      const verdict = evaluate(event.sample, ex.rules);
      state.reps.push({
        index: event.index,
        level: verdict.level,
        text: verdict.text,
        primaryMin: event.sample.getMin("primary"),
        kneeMin: event.sample.getMin("knee"),
        hipMin: event.sample.getMin("hip"),
        shoulderMax: event.sample.getMax("shoulder"),
        torsoMax: event.sample.getMax("torso_vertical"),
      });
      if (verdict.level === "good") state.stats.good++;
      else if (verdict.level === "warn") state.stats.warn++;
      else state.stats.bad++;

      document.getElementById("hud-reps").textContent = state.repCounter.count;
      updateRing(state.repCounter.count, ex.repGoal, verdict.level);
      setCoach(verdict.text, verdict.level, null);
      pushFeedback(verdict.text, verdict.level, null);

      const uid = currentUserId() || "u_anon";
      appendRep(uid, state.sessionId, {
        index: event.index, level: verdict.level, text: verdict.text,
        primary_min: event.sample.getMin("primary"),
        knee_min: event.sample.getMin("knee"),
        hip_min: event.sample.getMin("hip"),
        torso_max: event.sample.getMax("torso_vertical"),
      });

      maybeAskCoach(ex, verdict, event.sample.metrics, uid);
    }
  }
  state.loopHandle = requestAnimationFrame(loop);
}

async function maybeAskCoach(ex, verdict, metrics, uid) {
  const now = Date.now();
  if (now - state.lastCoachTs < 2500) return;
  state.lastCoachTs = now;
  try {
    const resp = await requestCoach({
      exercise: ex.name,
      verdictLevel: verdict.level,
      verdictText: verdict.text,
      metrics,
      userId: uid,
      onPending: () => setCoachPending(true),
    });
    setCoachPending(false);
    if (resp && resp.authError) {
      toast("Sign-in expired. Please sign in again.");
      signOut();
      refreshSignInLabel();
      openSignInModal();
      return;
    }
    if (resp && resp.rateLimited) {
      toast("Coach rate limit hit - showing rule feedback only.");
      return;
    }
    if (resp && resp.text) {
      setCoach(resp.text, verdict.level, resp.sourceUrl);
      pushFeedback(resp.text, verdict.level, resp.sourceUrl);
    }
  } catch (_) {
    setCoachPending(false);
  }
}

// ============================================================ HUD
function updateRing(count, goal, level) {
  const ring = document.querySelector(".hud-ring");
  if (level) ring.dataset.level = level;
  const pct = Math.max(0, Math.min(1, goal ? count / goal : 0));
  const dash = 263.9;
  document.getElementById("ring-fill").style.strokeDashoffset =
    (dash * (1 - pct)).toFixed(1);
}

/**
 * Live depth indicator - fills from 0% (angle at standing) to 100%
 * (angle at bottom target). Runs every frame, not only at rep-close,
 * so the user can see how deep they are going in real time.
 */
function updateDepthIndicator(primary, ex) {
  const bar = document.getElementById("depth-fill");
  const pctEl = document.getElementById("depth-pct");
  if (!bar || !pctEl) return;
  const { standingDeg, bottomDeg } = ex.repDef;
  const range = standingDeg - bottomDeg;
  let pct = 0;
  if (primary != null && range !== 0) {
    pct = ((standingDeg - primary) / range) * 100;
  }
  pct = Math.max(0, Math.min(120, pct));
  bar.style.width = `${Math.min(100, pct)}%`;
  bar.dataset.state = pct >= 100 ? "hit" : (pct >= 60 ? "close" : "");
  pctEl.textContent = `${Math.round(pct)}%`;
}

/**
 * Mid-rep form flash. Fires immediately when knee-over-toe or torso
 * lean crosses a threshold DURING the descent, without waiting for
 * the rep to close. Uses a data attribute on the ring that CSS turns
 * into a red pulse.
 */
function updateFormFlash(metrics, ex) {
  const ring = document.querySelector(".hud-ring");
  if (!ring) return;
  let warn = false;
  if (state.repCounter && state.repCounter.state === "BOTTOM") {
    if (metrics.knee_over_toe_norm != null
        && metrics.knee_over_toe_norm > 0.4) warn = true;
    if (metrics.torso_vertical != null
        && metrics.torso_vertical > 45) warn = true;
  }
  ring.dataset.formWarn = warn ? "true" : "false";
}

function setCoach(text, level, sourceUrl) {
  const banner = document.getElementById("coach-banner");
  banner.dataset.level = level || "idle";
  document.getElementById("coach-text").textContent = text || "";
  const src = document.getElementById("coach-source");
  if (sourceUrl) {
    src.href = sourceUrl;
    src.hidden = false;
  } else {
    src.hidden = true;
  }
}

function setCoachPending(on) {
  const pending = document.getElementById("coach-pending");
  if (pending) pending.hidden = !on;
}

function updateMini({ good, warn, elapsed }) {
  document.getElementById("mini-good").textContent = good;
  document.getElementById("mini-warn").textContent = warn;
  const m = Math.floor(elapsed / 60);
  const s = String(elapsed % 60).padStart(2, "0");
  document.getElementById("mini-elapsed").textContent = `${m}:${s}`;
}

function pushFeedback(text, level, sourceUrl) {
  const log = document.getElementById("feedback-log");
  const empty = log.querySelector(".feedback-empty");
  if (empty) empty.remove();
  const item = document.createElement("div");
  item.className = "feedback-item";
  item.dataset.level = level;
  const t = new Date().toLocaleTimeString(undefined,
    { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  item.innerHTML = `
    <div class="feedback-time">${t}</div>
    <div class="feedback-msg"></div>
    ${sourceUrl ? `<a class="feedback-src" href="${sourceUrl}" target="_blank" rel="noopener">source</a>` : ""}
  `;
  item.querySelector(".feedback-msg").textContent = text;
  log.prepend(item);
  const n = log.querySelectorAll(".feedback-item").length;
  document.getElementById("feedback-count").textContent = n;
  while (log.querySelectorAll(".feedback-item").length > 80) {
    log.querySelector(".feedback-item:last-child").remove();
  }
}

// ============================================================ END + SUMMARY
function endSession() {
  state.running = false;
  if (state.loopHandle) cancelAnimationFrame(state.loopHandle);
  if (state.timerHandle) clearInterval(state.timerHandle);
  if (state.stream) {
    state.stream.getTracks().forEach(t => t.stop());
    state.stream = null;
  }
  const uid = currentUserId() || "u_anon";
  if (state.sessionId) closeSession(uid, state.sessionId);

  // Fire-and-forget: try to send today's summary email. The VM
  // dedupes so extra sessions in the same day silently no-op.
  triggerDailyReport(uid, { silent: true });

  showSummary();
}

/**
 * Send the daily summary and surface the outcome. `silent` = true
 * suppresses success toasts (used on auto-send at end of session);
 * the summary button uses silent=false so the user sees confirmation.
 */
async function triggerDailyReport(uid, { silent = false } = {}) {
  const btn = document.getElementById("summary-send-report");
  if (btn && !silent) {
    btn.disabled = true;
    btn.dataset.state = "sending";
  }
  // closeSession already stamped endedAt on the just-finished session,
  // so pastSessions returns it - no need to snapshot separately.
  const all = pastSessions(uid, 200);
  const result = await sendDailyReport(uid, all);
  if (btn && !silent) {
    btn.disabled = false;
    btn.dataset.state = result.ok ? "sent" : "error";
  }
  if (silent) return;
  if (result.ok && result.sent) {
    toast("Daily summary emailed.");
  } else if (result.ok && result.sent === false) {
    toast("Today's summary already sent.");
  } else if (result.reason === "email-not-configured") {
    toast("Email not configured on the VM yet.");
  } else if (result.reason === "no-sessions-today") {
    toast("No sessions today to summarise.");
  } else if (result.reason === "rate-limited") {
    toast("Report rate limit hit - try again later.");
  } else {
    toast(`Report failed (${result.reason || "unknown"}).`);
  }
}

function showSummary() {
  setView("summary");
  const ex = EXERCISES[state.exerciseId];
  const total = state.reps.length;
  const good = state.stats.good;
  const warn = state.stats.warn;
  const bad = state.stats.bad;
  const goodPct = total ? Math.round(100 * good / total) : 0;
  const elapsed = Math.round((Date.now() - state.startedAt) / 1000);
  const mm = Math.floor(elapsed / 60);
  const ss = String(elapsed % 60).padStart(2, "0");

  document.getElementById("summary-title").textContent =
    total === 0 ? "No reps this time." :
    goodPct >= 80 ? "Nice work." :
    goodPct >= 50 ? "Solid session." :
    "You got started.";
  document.getElementById("summary-sub").textContent =
    total === 0
      ? "Try again when you are ready."
      : `${total} ${total === 1 ? "rep" : "reps"} of ${ex.name} in ${mm}:${ss}.`;

  const stats = document.getElementById("summary-stats");
  stats.innerHTML = "";
  addStat(stats, "Reps", total, "");
  addStat(stats, "Good form", `${goodPct}%`, "");
  addStat(stats, "Cues", warn + bad, "");
  const primaryMins = state.reps
    .map(r => r.primaryMin).filter(v => v != null);
  if (primaryMins.length) {
    const avg = primaryMins.reduce((a, b) => a + b, 0) / primaryMins.length;
    addStat(stats, `Avg ${primaryLabel(ex.repDef.primary)} min`,
            Math.round(avg), "°");
  }

  drawSummaryChart(ex);

  const tbody = document.getElementById("summary-rep-tbody");
  tbody.innerHTML = "";
  if (state.reps.length === 0) {
    tbody.innerHTML = `<tr><td colspan="4" style="text-align:center;color:var(--text-dim);padding:24px">No reps recorded</td></tr>`;
  } else {
    state.reps.forEach(r => {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td style="font-family:var(--font-mono)">${r.index}</td>
        <td style="font-family:var(--font-mono)">${r.primaryMin != null ? Math.round(r.primaryMin) + "°" : "-"}</td>
        <td class="rep-verdict rep-verdict-${r.level}">${r.level}</td>
        <td></td>
      `;
      tr.querySelector("td:last-child").textContent = r.text || "";
      tbody.appendChild(tr);
    });
  }
}

function addStat(container, label, value, unit) {
  const card = document.createElement("div");
  card.className = "stat-card";
  card.innerHTML = `
    <div class="stat-card-label">${label}</div>
    <div class="stat-card-value">${value}<span class="stat-card-unit">${unit || ""}</span></div>
  `;
  container.appendChild(card);
}

function drawSummaryChart(ex) {
  const canvas = document.getElementById("summary-chart");
  const ctx = canvas.getContext("2d");
  const DPR = window.devicePixelRatio || 1;
  const rect = canvas.getBoundingClientRect();
  const W = Math.max(320, rect.width) * DPR;
  const H = 200 * DPR;
  canvas.width = W;
  canvas.height = H;
  canvas.style.height = "200px";
  ctx.scale(DPR, DPR);
  const w = W / DPR, h = H / DPR;

  ctx.clearRect(0, 0, w, h);
  ctx.fillStyle = "#0a0d14";
  ctx.fillRect(0, 0, w, h);

  const reps = state.reps;
  if (!reps.length) {
    ctx.fillStyle = "#7c8698";
    ctx.font = "500 14px 'Inter', system-ui, sans-serif";
    ctx.textAlign = "center";
    ctx.fillText("No reps to chart yet.", w / 2, h / 2);
    return;
  }

  const values = reps.map(r => r.primaryMin || 0);
  const vmin = Math.min(...values, ex.repDef.bottomDeg - 10);
  const vmax = Math.max(...values, ex.repDef.standingDeg + 10);
  const pad = { l: 40, r: 20, t: 24, b: 30 };
  const cw = w - pad.l - pad.r;
  const ch = h - pad.t - pad.b;

  ctx.strokeStyle = "rgba(255,255,255,0.06)";
  ctx.lineWidth = 1;
  for (let i = 0; i <= 4; i++) {
    const y = pad.t + (ch * i / 4);
    ctx.beginPath();
    ctx.moveTo(pad.l, y);
    ctx.lineTo(w - pad.r, y);
    ctx.stroke();
  }
  const targetY = pad.t + ch * (1 - (ex.repDef.bottomDeg - vmin) / (vmax - vmin));
  ctx.strokeStyle = "rgba(52,211,153,0.5)";
  ctx.setLineDash([4, 4]);
  ctx.beginPath();
  ctx.moveTo(pad.l, targetY);
  ctx.lineTo(w - pad.r, targetY);
  ctx.stroke();
  ctx.setLineDash([]);
  ctx.fillStyle = "rgba(52,211,153,0.85)";
  ctx.font = "500 11px 'JetBrains Mono', monospace";
  ctx.textAlign = "left";
  ctx.fillText(`target ${ex.repDef.bottomDeg}°`, pad.l + 4, targetY - 4);

  const bw = cw / reps.length;
  reps.forEach((r, i) => {
    const v = r.primaryMin || vmin;
    const y = pad.t + ch * (1 - (v - vmin) / (vmax - vmin));
    const x = pad.l + i * bw + bw * 0.15;
    const barW = bw * 0.7;
    const color = r.level === "good" ? "#34d399"
                : r.level === "warn" ? "#fbbf24"
                : "#f87171";
    ctx.fillStyle = color;
    ctx.globalAlpha = 0.9;
    const barH = h - pad.b - y;
    ctx.beginPath();
    roundRect(ctx, x, y, barW, barH, 4);
    ctx.fill();
    ctx.globalAlpha = 1;
  });

  ctx.fillStyle = "#7c8698";
  ctx.font = "500 11px 'JetBrains Mono', monospace";
  ctx.textAlign = "right";
  ctx.fillText(Math.round(vmax) + "°", pad.l - 6, pad.t + 4);
  ctx.fillText(Math.round(vmin) + "°", pad.l - 6, h - pad.b);
  ctx.textAlign = "center";
  ctx.fillText("rep", w / 2, h - 8);
}

function roundRect(ctx, x, y, w, h, r) {
  ctx.moveTo(x + r, y);
  ctx.lineTo(x + w - r, y);
  ctx.quadraticCurveTo(x + w, y, x + w, y + r);
  ctx.lineTo(x + w, y + h - r);
  ctx.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
  ctx.lineTo(x + r, y + h);
  ctx.quadraticCurveTo(x, y + h, x, y + h - r);
  ctx.lineTo(x, y + r);
  ctx.quadraticCurveTo(x, y, x + r, y);
}

function wireSummary() {
  document.getElementById("summary-again")
    .addEventListener("click", () => beginSession(state.exerciseId));
  document.getElementById("summary-home")
    .addEventListener("click", () => setView("landing"));
  document.getElementById("summary-send-report")
    .addEventListener("click", async () => {
      const uid = currentUserId() || "u_anon";
      await triggerDailyReport(uid, { silent: false });
    });
}

// ============================================================ HISTORY DRAWER
function wireHistoryDrawer() {
  const drawer = document.getElementById("history-drawer");
  document.getElementById("nav-history").addEventListener("click", () => {
    const uid = currentUserId() || "u_anon";
    const sessions = pastSessions(uid, 30);
    const list = document.getElementById("history-list");
    list.innerHTML = "";
    if (!sessions.length) {
      list.innerHTML = `
        <div style="text-align:center;color:var(--text-dim);padding:60px 20px">
          No past sessions on this device yet.
        </div>`;
    } else {
      sessions.forEach(s => {
        const ex = EXERCISES[s.exercise] || { name: s.exercise };
        const started = new Date(s.startedAt).toLocaleString();
        const good = (s.reps || []).filter(r => r.level === "good").length;
        const total = (s.reps || []).length;
        const el = document.createElement("div");
        el.className = "history-item";
        el.innerHTML = `
          <div class="history-item-title">${ex.name || s.exercise}</div>
          <div class="history-item-meta">${started}</div>
          <div class="history-item-stats">
            <span><strong>${total}</strong> reps</span>
            <span><strong>${good}</strong> good</span>
          </div>
        `;
        list.appendChild(el);
      });
    }
    drawer.hidden = false;
  });
  document.getElementById("history-close")
    .addEventListener("click", () => { drawer.hidden = true; });
}

// ============================================================ SIGN IN
function wireSignIn() {
  const modal = document.getElementById("signin-modal");
  const form = document.getElementById("signin-form");
  const backdrop = document.getElementById("signin-backdrop");
  const errBox = document.getElementById("signin-error");
  const nameInput = document.getElementById("signin-name");
  const passInput = document.getElementById("signin-pass");
  const submitBtn = document.getElementById("signin-submit");
  const googleWrap = document.getElementById("signin-google");
  const googleHolder = document.getElementById("google-signin-button");

  // Only show the Google row when a client id is configured.
  if (CONFIG.googleClientId) {
    googleWrap.hidden = false;
    renderGoogleButton(googleHolder).then((profile) => {
      if (profile) {
        modal.hidden = true;
        refreshSignInLabel();
        toast(`Signed in as ${profile.email || profile.name || "you"}`);
      }
    }).catch((e) => {
      errBox.hidden = false;
      errBox.textContent = String(e.message || e);
    });
  }

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    errBox.hidden = true;
    submitBtn.disabled = true;
    submitBtn.style.opacity = "0.7";
    try {
      const profile = await signInWithPassphrase(
        passInput.value.trim(),
        nameInput.value.trim(),
      );
      modal.hidden = true;
      passInput.value = "";
      refreshSignInLabel();
      toast(`Welcome${profile && profile.display_name ? ", " + profile.display_name : ""}.`);
    } catch (err) {
      errBox.hidden = false;
      errBox.textContent = String(err.message || err);
    } finally {
      submitBtn.disabled = false;
      submitBtn.style.opacity = "1";
    }
  });

  // Backdrop no longer dismisses; the sign-in modal is required.
  backdrop.addEventListener("click", (e) => e.stopPropagation());
}

function wireNavSignIn() {
  const btn = document.getElementById("nav-signin");
  const menu = document.getElementById("user-menu");
  const wrap = btn.closest(".user-menu-wrap");
  const signoutBtn = document.getElementById("user-menu-signout");
  const nameEl = document.getElementById("user-menu-name");

  const closeMenu = () => {
    menu.hidden = true;
    if (wrap) wrap.dataset.open = "false";
  };
  const openMenu = () => {
    const profile = getSavedProfile();
    nameEl.textContent =
      (profile && (profile.display_name || profile.name || profile.email))
      || "You";
    menu.hidden = false;
    if (wrap) wrap.dataset.open = "true";
  };

  btn.addEventListener("click", (e) => {
    e.stopPropagation();
    if (!isSignedIn()) {
      openSignInModal();
      return;
    }
    if (menu.hidden) openMenu(); else closeMenu();
  });

  signoutBtn.addEventListener("click", (e) => {
    e.stopPropagation();
    signOut();
    refreshSignInLabel();
    closeMenu();
    toast("Signed out.");
    // If the user was mid-session, tear it down cleanly.
    if (state.running) endSession();
  });

  // Any click outside the menu closes it.
  document.addEventListener("click", (e) => {
    if (menu.hidden) return;
    if (menu.contains(e.target) || btn.contains(e.target)) return;
    closeMenu();
  });
  // Escape closes it too.
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closeMenu();
  });
}

function openSignInModal() {
  document.getElementById("signin-modal").hidden = false;
  const passInput = document.getElementById("signin-pass");
  if (passInput) setTimeout(() => passInput.focus(), 60);
}

// ============================================================ POSE / METRICS HELPERS
function pickPrimary(angles, ex) {
  const family = ex.repDef.primary;
  const dec = ex.repDef.bottomDeg < ex.repDef.standingDeg;
  const [a, b] =
    family === "knee"     ? [angles.knee_left, angles.knee_right] :
    family === "hip"      ? [angles.hip_left, angles.hip_right] :
    family === "shoulder" ? [angles.shoulder_left, angles.shoulder_right] :
    family === "elbow"    ? [angles.elbow_left, angles.elbow_right] :
    [null, null];
  // Bilateral exercises (squat, glute bridge) require BOTH sides to be
  // visible; otherwise a single-leg raise or a hand near the camera
  // would fake a rep. Returning null keeps the counter in STANDING.
  if (ex.repDef.bilateral) {
    if (a == null || b == null) return null;
    return dec ? Math.min(a, b) : Math.max(a, b);
  }
  if (a != null && b != null) return dec ? Math.min(a, b) : Math.max(a, b);
  return a != null ? a : b;
}

function buildMetrics(angles, decreasing) {
  const m = {};
  for (const n of ["knee_left", "knee_right"]) {
    const v = angles[n]; if (v == null) continue;
    m.knee = m.knee == null ? v : Math.min(m.knee, v);
  }
  for (const n of ["hip_left", "hip_right"]) {
    const v = angles[n]; if (v == null) continue;
    m.hip = m.hip == null ? v :
      (decreasing ? Math.min(m.hip, v) : Math.max(m.hip, v));
  }
  for (const n of ["elbow_left", "elbow_right"]) {
    const v = angles[n]; if (v == null) continue;
    m.elbow = m.elbow == null ? v : Math.min(m.elbow, v);
  }
  for (const n of ["shoulder_left", "shoulder_right"]) {
    const v = angles[n]; if (v == null) continue;
    m.shoulder = m.shoulder == null ? v : Math.max(m.shoulder, v);
  }
  if (angles.torso_vertical != null) m.torso_vertical = angles.torso_vertical;
  if (angles.torso_length) {
    for (const side of ["left", "right"]) {
      const kt = angles[`knee_over_toe_${side}`];
      if (kt != null) {
        const norm = kt / angles.torso_length;
        m.knee_over_toe_norm = m.knee_over_toe_norm == null
          ? norm : Math.max(m.knee_over_toe_norm, norm);
      }
    }
  }
  return m;
}

function primaryLabel(family) {
  return { knee: "Knee", hip: "Hip", shoulder: "Shoulder", elbow: "Elbow" }[family]
    || "Angle";
}

// ============================================================ ICONS
function iconSquat() {
  return `<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="4" r="1.5"/><path d="M12 6v6l-4 5v3"/><path d="M12 12l4 5v3"/><path d="M9 10l-3 -1"/><path d="M15 10l3 -1"/></svg>`;
}
function iconLunge() {
  return `<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="9" cy="4" r="1.5"/><path d="M9 6l0 6l-3 6"/><path d="M9 12l6 4l0 4"/></svg>`;
}
function iconBridge() {
  return `<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="5" cy="10" r="1.5"/><path d="M5 12l6 -3l5 3l0 4"/><path d="M11 9l0 4"/><path d="M3 20l18 0"/></svg>`;
}
function iconLeg() {
  return `<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="4" cy="14" r="1.5"/><path d="M6 14l6 -3l8 0"/><path d="M20 11l1 3"/><path d="M12 14l-2 6"/></svg>`;
}
function iconShoulder() {
  return `<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="4" r="1.5"/><path d="M12 6l0 8"/><path d="M6 6l6 2l6 -2"/><path d="M12 14l-2 6"/><path d="M12 14l2 6"/></svg>`;
}
function iconGeneric() {
  return `<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="4" r="1.5"/><path d="M12 6l0 12"/><path d="M8 10h8"/></svg>`;
}
