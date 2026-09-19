(function () {
  const tabs = document.querySelectorAll(".tab");
  tabs.forEach(t => t.addEventListener("click", () => {
    tabs.forEach(x => x.classList.remove("active"));
    t.classList.add("active");
    document.querySelectorAll(".pane").forEach(p =>
      p.classList.toggle("active", p.id === "tab-" + t.dataset.tab));
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
  };

  let lastMsg = "";
  function render(state) {
    el.status.textContent = state.running ? "פעיל" : "ממתין";
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
      el.status.textContent = "נותק";
    } finally {
      setTimeout(poll, 200);
    }
  }
  poll();
})();
