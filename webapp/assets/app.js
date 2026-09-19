/**
 * PhysioLive web app - entry point.
 * Three view states (data-view on <body>):
 *   - landing:  exercise picker + hero
 *   - live:     camera + skeleton + HUD + feedback
 *   - summary:  end-of-session stats + rep table
 */

import { EXERCISES } from "./exercises.js";
import { ensurePose, inferPose, drawSkeleton } from "./pose.js";
import { allAngles } from "./angles.js";
import { RepCounter } from "./rep_counter.js";
import { evaluate } from "./rules.js";
import { requestCoach } from "./coach_client.js";
import {
  currentUserId, promptSignIn, getSavedProfile, getOrCreateAnonId, signOut,
} from "./auth.js";
import {
  openSession, appendRep, closeSession, pastSessions, currentSession,
} from "./session.js";

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
};

// Meta / icons for the exercise cards.
const EX_META = {
  squat:              { view: "Front camera",     goal: "12 reps",    icon: iconSquat() },
  lunge:              { view: "Side camera",      goal: "10 reps",    icon: iconLunge() },
  glute_bridge:       { view: "Side camera",      goal: "12 reps",    icon: iconBridge() },
  leg_raise:          { view: "Side camera",      goal: "12 reps",    icon: iconLeg() },
  shoulder_abduction: { view: "Front camera",     goal: "15 reps",    icon: iconShoulder() },
};

// ============================================================ BOOT
window.addEventListener("DOMContentLoaded", () => {
  wireLanding();
  wireLive();
  wireSummary();
  wireHistoryDrawer();
  wireSignIn();
  const profile = getSavedProfile();
  if (profile) {
    document.getElementById("signin-label").textContent =
      (profile.name || "You").split(" ")[0];
  } else {
    getOrCreateAnonId();
  }
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
        <span>•</span>
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
}

async function beginSession(exerciseId) {
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
    const stream = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: { ideal: "user" }, width: 1280, height: 720 },
      audio: false,
    });
    state.stream = stream;
    state.video.srcObject = stream;
    await state.video.play();
    await ensurePose();
  } catch (e) {
    showLoading(false);
    setCoach(`Camera error: ${e.message || e}`, "bad", null);
    return;
  }
  showLoading(false);

  state.repCounter = new RepCounter(ex.repDef);
  state.reps = [];
  state.stats = { good: 0, warn: 0, bad: 0 };
  state.startedAt = Date.now();
  const uid = currentUserId();
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

async function loop() {
  if (!state.running) return;
  const ts = performance.now();
  const lm = await inferPose(state.video, ts);
  const w = state.video.videoWidth || state.canvas.width || 1280;
  const h = state.video.videoHeight || state.canvas.height || 720;
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
    document.getElementById("hud-phase").textContent = state.repCounter.state;
    document.getElementById("hud-angle").textContent =
      primary != null ? `${Math.round(primary)}°` : "--";

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
      speak(verdict.text);

      const uid = currentUserId();
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
    });
    if (resp && resp.text) {
      setCoach(resp.text, verdict.level, resp.sourceUrl);
      pushFeedback(resp.text, verdict.level, resp.sourceUrl);
      speak(resp.text);
    }
  } catch (_) { /* silent - rule text already shown */ }
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
  const uid = currentUserId();
  if (state.sessionId) closeSession(uid, state.sessionId);

  showSummary();
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

  // Stat cards.
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

  // Chart.
  drawSummaryChart(ex);

  // Rep table.
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

  // Grid + reference lines.
  ctx.strokeStyle = "rgba(255,255,255,0.06)";
  ctx.lineWidth = 1;
  for (let i = 0; i <= 4; i++) {
    const y = pad.t + (ch * i / 4);
    ctx.beginPath();
    ctx.moveTo(pad.l, y);
    ctx.lineTo(w - pad.r, y);
    ctx.stroke();
  }
  // Target band around bottom_deg.
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

  // Bars per rep.
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

  // Axis labels.
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
}

// ============================================================ HISTORY DRAWER
function wireHistoryDrawer() {
  const drawer = document.getElementById("history-drawer");
  document.getElementById("nav-history").addEventListener("click", () => {
    const uid = currentUserId();
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
  document.getElementById("nav-signin").addEventListener("click", async () => {
    const profile = getSavedProfile();
    if (profile) {
      signOut();
      document.getElementById("signin-label").textContent = "Sign in";
      toast("Signed out.");
      return;
    }
    modal.hidden = false;
    try {
      const p = await promptSignIn(
        document.getElementById("google-signin-button"));
      if (p) {
        document.getElementById("signin-label").textContent =
          (p.name || "You").split(" ")[0];
        toast(`Signed in as ${p.email || p.name}`);
        modal.hidden = true;
      }
    } catch (e) { console.warn(e); }
  });
  document.getElementById("signin-skip")
    .addEventListener("click", () => { modal.hidden = true; });
  document.getElementById("signin-backdrop")
    .addEventListener("click", () => { modal.hidden = true; });
}

// ============================================================ SPEECH
const speech = window.speechSynthesis;
let ttsVoice = null;
function speak(text) {
  if (!speech || !text) return;
  try {
    if (!ttsVoice) {
      const voices = speech.getVoices();
      ttsVoice = voices.find(v => v.lang.startsWith("en")) || voices[0] || null;
    }
    const u = new SpeechSynthesisUtterance(text);
    if (ttsVoice) u.voice = ttsVoice;
    u.rate = 1.05;
    speech.cancel();
    speech.speak(u);
  } catch (_) { /* silent */ }
}
if (speech) speech.onvoiceschanged = () => { ttsVoice = null; };

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
