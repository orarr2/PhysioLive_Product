/**
 * PhysioLive web app entry point. Wires the camera, the pose backend,
 * the rep counter, the rule engine, the voice output, the coach client
 * and the client-side session log.
 */

import { EXERCISES } from "./exercises.js";
import { ensurePose, inferPose, drawSkeleton } from "./pose.js";
import { allAngles } from "./angles.js";
import { RepCounter } from "./rep_counter.js";
import { evaluate } from "./rules.js";
import { requestCoach } from "./coach_client.js";
import { currentUserId, promptSignIn, getSavedProfile, getOrCreateAnonId }
  from "./auth.js";
import { openSession, appendRep, closeSession } from "./session.js";

const state = {
  running: false,
  exerciseId: "squat",
  repCounter: null,
  sessionId: null,
  stats: { reps: 0, good: 0, warn: 0 },
  video: null,
  canvas: null,
  ctx: null,
  stream: null,
  loopHandle: null,
  lastVerdictText: "",
  lastVerdictLevel: "",
};

const el = {
  stage: document.getElementById("stage"),
  video: document.getElementById("cam"),
  canvas: document.getElementById("overlay"),
  cameraBtn: document.getElementById("camera-btn"),
  signInBtn: document.getElementById("signin-btn"),
  exerciseSelect: document.getElementById("exercise-select"),
  exerciseName: document.getElementById("exercise-name"),
  repCount: document.getElementById("rep-count"),
  repGoal: document.getElementById("rep-goal"),
  repState: document.getElementById("rep-state"),
  primaryAngle: document.getElementById("primary-angle"),
  verdict: document.getElementById("verdict"),
  log: document.getElementById("feedback-log"),
  signInModal: document.getElementById("signin-modal"),
  signInSkip: document.getElementById("signin-skip"),
  googleButton: document.getElementById("google-signin-button"),
  statReps: document.getElementById("stat-reps"),
  statGood: document.getElementById("stat-good"),
  statWarn: document.getElementById("stat-warn"),
};

state.video = el.video;
state.canvas = el.canvas;
state.ctx = el.canvas.getContext("2d");

const speech = window.speechSynthesis;
let voice = null;
function speak(text) {
  if (!text || !speech) return;
  try {
    if (!voice) {
      const voices = speech.getVoices();
      voice = voices.find((v) => v.lang.startsWith("en")) || voices[0] || null;
    }
    const utter = new SpeechSynthesisUtterance(text);
    if (voice) utter.voice = voice;
    utter.rate = 1.05;
    speech.cancel();
    speech.speak(utter);
  } catch (_) { /* ignore */ }
}
if (speech) {
  speech.onvoiceschanged = () => { voice = null; };
}

function pickPrimary(angles, exercise) {
  const family = exercise.repDef.primary;
  const dec = exercise.repDef.bottomDeg < exercise.repDef.standingDeg;
  const [a, b] = family === "knee"
    ? [angles.knee_left, angles.knee_right]
    : family === "hip"
    ? [angles.hip_left, angles.hip_right]
    : family === "shoulder"
    ? [angles.shoulder_left, angles.shoulder_right]
    : family === "elbow"
    ? [angles.elbow_left, angles.elbow_right]
    : [null, null];
  if (a != null && b != null) {
    if (dec) return a <= b ? a : b;
    return a >= b ? a : b;
  }
  return a != null ? a : b;
}

function buildMetrics(angles, decreasing) {
  const m = {};
  for (const n of ["knee_left", "knee_right"]) {
    const v = angles[n];
    if (v == null) continue;
    m.knee = m.knee == null ? v : Math.min(m.knee, v);
  }
  for (const n of ["hip_left", "hip_right"]) {
    const v = angles[n];
    if (v == null) continue;
    m.hip = m.hip == null ? v
      : decreasing ? Math.min(m.hip, v) : Math.max(m.hip, v);
  }
  for (const n of ["elbow_left", "elbow_right"]) {
    const v = angles[n];
    if (v == null) continue;
    m.elbow = m.elbow == null ? v : Math.min(m.elbow, v);
  }
  for (const n of ["shoulder_left", "shoulder_right"]) {
    const v = angles[n];
    if (v == null) continue;
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

function log(text, level, sourceUrl) {
  const msg = document.createElement("div");
  msg.className = "msg";
  const t = new Date().toLocaleTimeString();
  msg.textContent = `[${t}] ${text}`;
  if (sourceUrl) {
    const a = document.createElement("a");
    a.className = "source";
    a.href = sourceUrl; a.target = "_blank"; a.rel = "noopener";
    a.textContent = "source";
    msg.appendChild(a);
  }
  el.log.prepend(msg);
  while (el.log.childElementCount > 80) el.log.lastElementChild.remove();
}

function setupExercise() {
  const ex = EXERCISES[state.exerciseId];
  state.repCounter = new RepCounter(ex.repDef);
  el.exerciseName.textContent = ex.name;
  el.repGoal.textContent = ex.repGoal;
  el.repCount.textContent = "0";
  el.repState.textContent = "STANDING";
  state.stats = { reps: 0, good: 0, warn: 0 };
  updateStats();
}

function updateStats() {
  el.statReps.textContent = state.stats.reps;
  el.statGood.textContent = state.stats.good;
  el.statWarn.textContent = state.stats.warn;
}

async function startCamera() {
  const stream = await navigator.mediaDevices.getUserMedia({
    video: { facingMode: { ideal: "user" }, width: 1280, height: 720 },
    audio: false,
  });
  state.stream = stream;
  state.video.srcObject = stream;
  await state.video.play();
  await ensurePose();
  setupExercise();
  const uid = currentUserId();
  state.sessionId = openSession(uid, state.exerciseId);
  state.running = true;
  el.stage.classList.add("active");
  el.cameraBtn.textContent = "Stop";
  loop();
}

function stopCamera() {
  state.running = false;
  if (state.stream) {
    state.stream.getTracks().forEach((t) => t.stop());
    state.stream = null;
  }
  if (state.loopHandle) cancelAnimationFrame(state.loopHandle);
  const uid = currentUserId();
  if (state.sessionId) {
    closeSession(uid, state.sessionId);
    state.sessionId = null;
  }
  el.stage.classList.remove("active");
  el.cameraBtn.textContent = "Camera";
}

async function loop() {
  if (!state.running) return;
  const ts = performance.now();
  const lm = await inferPose(state.video, ts);
  const w = state.video.videoWidth || state.canvas.width;
  const h = state.video.videoHeight || state.canvas.height;
  if (state.canvas.width !== w) state.canvas.width = w;
  if (state.canvas.height !== h) state.canvas.height = h;
  state.ctx.clearRect(0, 0, w, h);
  if (lm) drawSkeleton(state.ctx, lm, w, h);

  if (lm) {
    const ex = EXERCISES[state.exerciseId];
    const angles = allAngles(lm);
    const primary = pickPrimary(angles, ex);
    const metrics = buildMetrics(angles, ex.repDef.bottomDeg < ex.repDef.standingDeg);
    const event = state.repCounter.update(primary, metrics);
    el.repState.textContent = state.repCounter.state;
    el.primaryAngle.textContent = primary != null
      ? `${Math.round(primary)}°` : "-";
    if (event) {
      const verdict = evaluate(event.sample, ex.rules);
      state.lastVerdictText = verdict.text;
      state.lastVerdictLevel = verdict.level;
      el.repCount.textContent = state.repCounter.count;
      el.verdict.className = `verdict ${verdict.level}`;
      el.verdict.textContent = verdict.text;
      state.stats.reps++;
      if (verdict.level === "good") state.stats.good++;
      else state.stats.warn++;
      updateStats();
      log(verdict.text, verdict.level);
      speak(verdict.text);
      const uid = currentUserId();
      appendRep(uid, state.sessionId, {
        index: event.index,
        level: verdict.level,
        text: verdict.text,
        knee_min: event.sample.getMin("knee"),
        hip_min: event.sample.getMin("hip"),
        primary_min: event.sample.getMin("primary"),
        torso_max: event.sample.getMax("torso_vertical"),
      });
      const coach = await requestCoach({
        exercise: ex.name,
        verdictLevel: verdict.level,
        verdictText: verdict.text,
        metrics: event.sample.metrics,
        userId: uid,
      });
      if (coach && coach.text) {
        el.verdict.textContent = coach.text;
        log(coach.text, verdict.level, coach.sourceUrl);
        speak(coach.text);
      }
    }
  }
  state.loopHandle = requestAnimationFrame(loop);
}

el.cameraBtn.addEventListener("click", () => {
  if (state.running) stopCamera();
  else startCamera().catch((e) => {
    log(`Camera error: ${e.message || e}`, "bad");
    el.stage.classList.remove("active");
  });
});

el.exerciseSelect.addEventListener("change", (e) => {
  state.exerciseId = e.target.value;
  if (state.running) {
    stopCamera();
  } else {
    setupExercise();
  }
});

el.signInBtn.addEventListener("click", async () => {
  el.signInModal.classList.remove("hidden");
  const profile = await promptSignIn(el.googleButton);
  if (profile) {
    el.signInBtn.textContent = profile.name.split(" ")[0] || "Signed in";
    el.signInModal.classList.add("hidden");
    log(`Signed in as ${profile.email}`, "good");
  }
});
el.signInSkip.addEventListener("click", () => {
  el.signInModal.classList.add("hidden");
});

const savedProfile = getSavedProfile();
if (savedProfile) {
  el.signInBtn.textContent = (savedProfile.name || "").split(" ")[0]
    || "Signed in";
} else {
  getOrCreateAnonId();
}

setupExercise();
