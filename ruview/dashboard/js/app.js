/**
 * Unified House Dashboard — app logic.
 */
(function () {
  // ── Clock ──────────────────────────────────────────────────────────────────
  const clockEl = document.getElementById("clock");
  function tickClock() {
    const d = new Date();
    clockEl.textContent =
      d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  }
  tickClock();
  setInterval(tickClock, 1000);

  // ── LED state ──────────────────────────────────────────────────────────────
  let ledTarget     = "all";
  let ledPreset     = "off";
  let ledBrightness = 160;
  let ledColor      = "#ff5020";
  let ledSendTimer  = null;

  // ── AC state ──────────────────────────────────────────────────────────────
  let acPowerState = "off";
  let acMode       = "cool";
  let acTemp       = 25;
  let acFan        = "auto";

  // ── DOM refs ──────────────────────────────────────────────────────────────
  const wsBadge        = document.getElementById("ws-badge");
  const ledNodesEl     = document.getElementById("led-nodes");
  const brightnessEl   = document.getElementById("brightness-slider");
  const brightnessVal  = document.getElementById("brightness-val");
  const colorPicker    = document.getElementById("color-picker");
  const colorHex       = document.getElementById("color-hex");
  const customRow      = document.getElementById("custom-row");
  const ledFeedback    = document.getElementById("led-feedback");
  const acTempVal      = document.getElementById("ac-temp-val");
  const acFeedback     = document.getElementById("ac-feedback");
  const lightFeedback  = document.getElementById("light-feedback");
  const irDot          = document.getElementById("ir-status");

  // ── WebSocket status ──────────────────────────────────────────────────────
  window.addEventListener("ruview-connected", () => {
    wsBadge.textContent = "Live";
    wsBadge.className   = "badge badge--online";
    pollLedNodes();
    pollIrStatus();
  });
  window.addEventListener("ruview-disconnected", () => {
    wsBadge.textContent = "Offline";
    wsBadge.className   = "badge badge--offline";
  });

  // ── Human-detection updates (forwarded from ws.js) ────────────────────────
  window.addEventListener("ruview-update", (evt) => {
    const d = evt.detail;
    updatePresence(d.presence);
    updateVitals(d.vitals);
    updateCsiNodes(d.nodes);
    updateSystemStats(d);
  });

  // ══════════════════════════════════════════════════════════════════════════
  //  LED CONTROLS
  // ══════════════════════════════════════════════════════════════════════════

  // Target pills
  document.getElementById("led-target").addEventListener("click", (e) => {
    const btn = e.target.closest(".pill");
    if (!btn) return;
    ledTarget = btn.dataset.val;
    setPillActive("led-target", ledTarget);
  });

  // Preset buttons
  document.getElementById("preset-grid").addEventListener("click", (e) => {
    const btn = e.target.closest(".preset-btn");
    if (!btn) return;
    ledPreset = btn.dataset.preset;
    setPresetActive(ledPreset);
    customRow.style.display = ledPreset === "custom" ? "flex" : "none";
    sendLed();
  });

  // Brightness slider
  brightnessEl.addEventListener("input", () => {
    ledBrightness = parseInt(brightnessEl.value);
    brightnessVal.textContent = ledBrightness;
    scheduleLedSend();
  });
  brightnessEl.addEventListener("change", sendLed);

  // Color picker
  colorPicker.addEventListener("input", () => {
    ledColor = colorPicker.value;
    colorHex.textContent = ledColor;
    if (ledPreset === "custom") scheduleLedSend();
  });
  colorPicker.addEventListener("change", () => {
    if (ledPreset === "custom") sendLed();
  });

  function scheduleLedSend() {
    clearTimeout(ledSendTimer);
    ledSendTimer = setTimeout(sendLed, 400);
  }

  async function sendLed() {
    clearTimeout(ledSendTimer);
    const body = { target: ledTarget, preset: ledPreset, brightness: ledBrightness };
    if (ledPreset === "custom") {
      const { r, g, b } = hexToRgb(ledColor);
      body.r = r; body.g = g; body.b = b;
    }
    try {
      const res  = await fetch("/api/v1/led/set", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Error");
      setFeedback(ledFeedback, `Sent → ${ledPreset}  brightness ${ledBrightness}`, "ok");
    } catch (e) {
      setFeedback(ledFeedback, `Failed: ${e.message}`, "err");
    }
  }

  async function pollLedNodes() {
    try {
      const res  = await fetch("/api/v1/led/nodes");
      const data = await res.json();
      renderLedNodes(data);
    } catch (_) {}
    setTimeout(pollLedNodes, 10000);
  }

  function renderLedNodes(nodes) {
    const ids = ["led_1", "led_2", "led_3"];
    ledNodesEl.innerHTML = ids.map(id => {
      const n   = nodes[id];
      const on  = n && n.online;
      const pre = n ? n.preset : "—";
      return `<div class="led-node-chip">
        <span class="led-dot ${on ? "led-dot--online" : "led-dot--offline"}"></span>
        <span>${id.replace("_", " ")} · ${pre}</span>
      </div>`;
    }).join("");
  }

  // ══════════════════════════════════════════════════════════════════════════
  //  AC CONTROLS
  // ══════════════════════════════════════════════════════════════════════════

  window.acPower = function (p) {
    acPowerState = p;
    document.getElementById("ac-on").classList.toggle("active",  p === "on");
    document.getElementById("ac-off").classList.toggle("active", p === "off");
  };

  window.acTempDelta = function (d) {
    acTemp = Math.max(16, Math.min(30, acTemp + d));
    acTempVal.textContent = acTemp;
  };

  document.getElementById("ac-mode").addEventListener("click", (e) => {
    const btn = e.target.closest(".pill");
    if (!btn) return;
    acMode = btn.dataset.val;
    setPillActive("ac-mode", acMode);
  });

  document.getElementById("ac-fan").addEventListener("click", (e) => {
    const btn = e.target.closest(".pill");
    if (!btn) return;
    acFan = btn.dataset.val;
    setPillActive("ac-fan", acFan);
  });

  window.acSend = async function () {
    const btn = document.getElementById("ac-send-btn");
    btn.disabled = true;
    try {
      const res  = await fetch("/api/v1/ir/ac", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ power: acPowerState, mode: acMode, temp: acTemp, fan: acFan }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "IR error");
      setFeedback(acFeedback, `Sent: ${acPowerState} · ${acMode} · ${acTemp}°C · ${acFan}`, "ok");
    } catch (e) {
      setFeedback(acFeedback, `Failed: ${e.message}`, "err");
    } finally {
      btn.disabled = false;
    }
  };

  async function pollIrStatus() {
    try {
      const res  = await fetch("/api/v1/ir/status");
      const data = await res.json();
      irDot.className = `ir-dot ${data.online ? "ir-dot--online" : "ir-dot--offline"}`;
      if (data.online) {
        acPowerState = data.ac.power;
        acMode       = data.ac.mode;
        acTemp       = data.ac.temp;
        acFan        = data.ac.fan;
        acTempVal.textContent = acTemp;
        document.getElementById("ac-on").classList.toggle("active",  acPowerState === "on");
        document.getElementById("ac-off").classList.toggle("active", acPowerState === "off");
        setPillActive("ac-mode", acMode);
        setPillActive("ac-fan",  acFan);
        const lp = data.light && data.light.power;
        if (lp) setLightActive(lp);
      }
    } catch (_) {}
    setTimeout(pollIrStatus, 15000);
  }

  // ══════════════════════════════════════════════════════════════════════════
  //  ROOM LIGHT CONTROLS
  // ══════════════════════════════════════════════════════════════════════════

  window.lightSet = async function (power) {
    setLightActive(power);
    try {
      const res  = await fetch("/api/v1/ir/light", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ power }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "IR error");
      setFeedback(lightFeedback, `Light ${power}`, "ok");
    } catch (e) {
      setFeedback(lightFeedback, `Failed: ${e.message}`, "err");
    }
  };

  function setLightActive(power) {
    document.getElementById("light-on-btn").classList.toggle("active",  power === "on");
    document.getElementById("light-off-btn").classList.toggle("active", power === "off");
  }

  // ══════════════════════════════════════════════════════════════════════════
  //  HUMAN DETECTION (dormant — preserved)
  // ══════════════════════════════════════════════════════════════════════════

  function updatePresence(p) {
    if (!p) return;
    const icon  = document.getElementById("presence-icon");
    const label = document.getElementById("presence-label");
    const conf  = document.getElementById("presence-conf");
    const zone  = document.getElementById("presence-zone");
    if (!icon) return;
    icon.className  = `presence-icon ${p.present ? "presence-icon--present" : "presence-icon--absent"}`;
    label.textContent = p.present ? "Person detected" : "No one detected";
    conf.textContent  = `Confidence: ${Math.round((p.confidence || 0) * 100)}%`;
    zone.textContent  = p.zone ? p.zone.replace(/_/g, " ") : "";
  }

  function updateVitals(v) {
    if (!v) return;
    const br = document.getElementById("breathing-rate");
    const hr = document.getElementById("heart-rate");
    if (br) br.textContent = v.breathing_rate > 0 ? v.breathing_rate.toFixed(1) : "--";
    if (hr) hr.textContent = v.heart_rate     > 0 ? v.heart_rate.toFixed(0)     : "--";
  }

  function updateCsiNodes(nodes) {
    const el = document.getElementById("nodes-list");
    if (!el || !nodes) return;
    el.innerHTML = Object.entries(nodes).map(([id, n]) => `
      <div class="node-row">
        <span class="node-dot ${n.online ? "node-dot--online" : "node-dot--offline"}"></span>
        <span class="node-id">${id}</span>
        <span class="node-rssi">${n.rssi} dBm</span>
        <span class="node-buf">${n.buffer_fill}/30</span>
      </div>`).join("");
  }

  function updateSystemStats(d) {
    const latEl  = document.getElementById("latency");
    const infEl  = document.getElementById("inf-count");
    const upEl   = document.getElementById("uptime");
    const calEl  = document.getElementById("calibrated");
    if (latEl) latEl.textContent  = d.inference_latency_ms != null ? `${d.inference_latency_ms.toFixed(1)}ms` : "--";
    if (infEl) infEl.textContent  = d.inference_count != null ? d.inference_count.toLocaleString() : "--";
    if (upEl)  upEl.textContent   = d.uptime_s != null ? formatUptime(d.uptime_s) : "--";
    if (calEl) calEl.textContent  = d.calibrated ? "Yes" : "No";
  }

  const calibrateBtn = document.getElementById("calibrate-btn");
  if (calibrateBtn) {
    calibrateBtn.addEventListener("click", async () => {
      calibrateBtn.disabled = true;
      calibrateBtn.textContent = "Calibrating (keep room empty)...";
      try {
        const res  = await fetch("/api/v1/calibrate", { method: "POST" });
        const data = await res.json();
        calibrateBtn.textContent = data.message || "Done";
        setTimeout(() => { calibrateBtn.textContent = "Calibrate Room"; calibrateBtn.disabled = false; }, 12000);
      } catch {
        calibrateBtn.textContent = "Error — retry";
        calibrateBtn.disabled = false;
      }
    });
  }

  // ══════════════════════════════════════════════════════════════════════════
  //  UTILITY
  // ══════════════════════════════════════════════════════════════════════════

  function setPillActive(groupId, val) {
    document.querySelectorAll(`#${groupId} .pill`).forEach(btn => {
      btn.classList.toggle("pill--active", btn.dataset.val === val);
    });
  }

  function setPresetActive(preset) {
    document.querySelectorAll(".preset-btn").forEach(btn => {
      btn.classList.toggle("preset-btn--active", btn.dataset.preset === preset);
    });
  }

  function setFeedback(el, msg, type) {
    el.textContent  = msg;
    el.className    = `feedback feedback--${type}`;
    setTimeout(() => { el.textContent = ""; el.className = "feedback"; }, 4000);
  }

  function hexToRgb(hex) {
    const r = parseInt(hex.slice(1, 3), 16);
    const g = parseInt(hex.slice(3, 5), 16);
    const b = parseInt(hex.slice(5, 7), 16);
    return { r, g, b };
  }

  function formatUptime(s) {
    if (s < 60) return `${Math.round(s)}s`;
    if (s < 3600) return `${Math.floor(s / 60)}m`;
    return `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m`;
  }
})();
