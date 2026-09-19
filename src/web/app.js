(function () {
  const tabs = document.querySelectorAll(".tab");
  tabs.forEach(t => t.addEventListener("click", () => {
    tabs.forEach(x => x.classList.remove("active"));
    t.classList.add("active");
    document.querySelectorAll(".pane").forEach(p =>
      p.classList.toggle("active", p.id === "tab-" + t.dataset.tab));
    if (t.dataset.tab === "session") loadSession();
    if (t.dataset.tab === "progress") loadProgress();
  }));

  const el = {
    status: document.getElementById("status"),
    exerciseName: document.getElementById("exercise-name"),
    repCount: document.getElementById("rep-count"),
    repGoal: document.getElementById("rep-goal"),
    repState: document.getElementById("rep-state"),
    kneeAngle: document.getElementById("knee-angle"),
    verdict: document.getElementById("verdict"),
    log: document.getElementById("feedback-log"),
    sessionBody: document.getElementById("session-body"),
    progressBody: document.getElementById("progress-body"),
  };

  let lastMsg = "";
  function render(state) {
    el.status.textContent = state.running ? "Live" : "Idle";
    el.exerciseName.textContent = state.exercise || "-";
    el.repCount.textContent = state.rep_count ?? 0;
    el.repGoal.textContent = state.rep_goal ?? "-";
    el.repState.textContent = state.rep_state || "-";
    if (state.knee_angle != null) {
      el.kneeAngle.textContent = Math.round(state.knee_angle) + "°";
    } else {
      el.kneeAngle.textContent = "-";
    }
    const v = state.verdict || {};
    el.verdict.className = "verdict " + (v.level || "");
    el.verdict.textContent = v.text || "";
    if (v.text && v.text !== lastMsg) {
      const msg = document.createElement("div");
      msg.className = "msg";
      const t = new Date().toLocaleTimeString();
      msg.textContent = `[${t}] ${v.text}`;
      if (v.source_url) {
        const a = document.createElement("a");
        a.href = v.source_url;
        a.target = "_blank";
        a.rel = "noopener";
        a.className = "source";
        a.textContent = "source";
        msg.appendChild(a);
      }
      el.log.prepend(msg);
      while (el.log.childElementCount > 80) el.log.lastElementChild.remove();
      lastMsg = v.text;
    }
  }

  async function poll() {
    try {
      const r = await fetch("/api/state", { cache: "no-store" });
      if (r.ok) render(await r.json());
    } catch (e) {
      el.status.textContent = "Offline";
    } finally {
      setTimeout(poll, 200);
    }
  }
  poll();

  async function loadSession() {
    try {
      const r = await fetch("/api/session", { cache: "no-store" });
      if (!r.ok) return;
      const data = await r.json();
      renderSession(data);
    } catch (_) {
      /* endpoint appears once session persistence lands. */
    }
  }

  function renderSession(data) {
    if (!data || !data.reps || !data.reps.length) {
      el.sessionBody.innerHTML =
        '<p class="empty">No reps recorded yet.</p>';
      return;
    }
    const good = data.reps.filter(r => r.level === "good").length;
    const rom = data.reps
      .map(r => r.knee_min_deg).filter(v => v != null);
    const romAvg = rom.length ? Math.round(rom.reduce((a, b) =>
      a + b, 0) / rom.length) : "-";
    let html = `
      <div class="stat-grid">
        <div class="stat-card"><div class="k">Reps</div>
          <div class="v">${data.reps.length}</div></div>
        <div class="stat-card"><div class="k">Good form</div>
          <div class="v">${good}</div></div>
        <div class="stat-card"><div class="k">Avg knee min</div>
          <div class="v">${romAvg}°</div></div>
        <div class="stat-card"><div class="k">Started</div>
          <div class="v">${data.started_at || "-"}</div></div>
      </div>
      <table class="rep-table"><thead><tr>
        <th>#</th><th>Knee min</th><th>Torso lean</th>
        <th>Verdict</th><th>Note</th>
      </tr></thead><tbody>`;
    data.reps.forEach((r, i) => {
      const kmin = r.knee_min_deg != null ? Math.round(r.knee_min_deg) : "-";
      const lean = r.torso_max_deg != null ? Math.round(r.torso_max_deg) : "-";
      html += `<tr>
        <td>${i + 1}</td>
        <td>${kmin}°</td>
        <td>${lean}°</td>
        <td class="lvl-${r.level || ""}">${r.level || "-"}</td>
        <td>${r.text || ""}</td>
      </tr>`;
    });
    html += "</tbody></table>";
    el.sessionBody.innerHTML = html;
  }

  async function loadProgress() {
    try {
      const r = await fetch("/api/progress", { cache: "no-store" });
      if (!r.ok) return;
      const data = await r.json();
      renderProgress(data);
    } catch (_) {
      /* endpoint appears once persistence lands. */
    }
  }

  function renderProgress(data) {
    if (!data || !data.sessions || !data.sessions.length) {
      el.progressBody.innerHTML =
        '<p class="empty">No prior sessions yet.</p>';
      return;
    }
    let html = `<table class="rep-table"><thead><tr>
      <th>Started</th><th>Exercise</th><th>Reps</th>
      <th>Good</th><th>Avg knee min</th></tr></thead><tbody>`;
    data.sessions.forEach(s => {
      html += `<tr>
        <td>${s.started_at}</td>
        <td>${s.exercise}</td>
        <td>${s.rep_count}</td>
        <td>${s.good_count}</td>
        <td>${s.avg_knee_min != null
              ? Math.round(s.avg_knee_min) + "°" : "-"}</td>
      </tr>`;
    });
    html += "</tbody></table>";
    el.progressBody.innerHTML = html;
  }
})();
