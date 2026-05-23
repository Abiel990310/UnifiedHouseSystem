/**
 * RuView Dashboard — main app logic.
 *
 * Consumes 'ruview-update' and 'ruview-connected/disconnected' events
 * and updates all UI elements + mini charts.
 */

(function () {
  // ── Mini chart state ─────────────────────────────────────────────────────
  const CHART_LEN = 60;  // data points (~6s at 10Hz, sampled at 1Hz)

  const motionData    = new Array(CHART_LEN).fill(0);
  const breathingData = new Array(CHART_LEN).fill(0);
  let lastSampleTime  = 0;

  // ── DOM refs ─────────────────────────────────────────────────────────────
  const wsBadge        = document.getElementById("ws-badge");
  const inferenceRate  = document.getElementById("inference-rate");
  const presenceIcon   = document.getElementById("presence-icon");
  const presenceLabel  = document.getElementById("presence-label");
  const presenceConf   = document.getElementById("presence-conf");
  const presenceZone   = document.getElementById("presence-zone");
  const confBar        = document.getElementById("confidence-bar");
  const breathingRate  = document.getElementById("breathing-rate");
  const heartRate      = document.getElementById("heart-rate");
  const breathingConf  = document.getElementById("breathing-conf");
  const heartConf      = document.getElementById("heart-conf");
  const nodesList      = document.getElementById("nodes-list");
  const latencyEl      = document.getElementById("latency");
  const infCountEl     = document.getElementById("inf-count");
  const uptimeEl       = document.getElementById("uptime");
  const calibratedEl   = document.getElementById("calibrated");
  const calibrateBtn   = document.getElementById("calibrate-btn");
  const motionCanvas   = document.getElementById("motion-chart");
  const breathCanvas   = document.getElementById("breathing-chart");

  const motionCtx  = motionCanvas.getContext("2d");
  const breathCtx  = breathCanvas.getContext("2d");

  // ── WebSocket status ─────────────────────────────────────────────────────
  window.addEventListener("ruview-connected", () => {
    wsBadge.textContent = "Live";
    wsBadge.className   = "badge badge--online";
  });
  window.addEventListener("ruview-disconnected", () => {
    wsBadge.textContent = "Offline";
    wsBadge.className   = "badge badge--offline";
  });

  // ── Main update handler ───────────────────────────────────────────────────
  window.addEventListener("ruview-update", (evt) => {
    const d = evt.detail;

    // Throttle chart / slow-DOM updates to 1Hz
    const now = Date.now();
    const doSlow = (now - lastSampleTime) >= 1000;
    if (doSlow) lastSampleTime = now;

    updatePresence(d.presence);
    updateVitals(d.vitals, doSlow);
    updateNodes(d.nodes);
    updateSystem(d);
    if (doSlow) {
      updateMotionChart(d);
      updateBreathingChart(d.vitals);
    }
  });

  // ── Presence ──────────────────────────────────────────────────────────────
  function updatePresence(p) {
    if (!p) return;
    const present = p.present;
    const conf    = p.confidence || 0;
    const pct     = Math.round(conf * 100);

    presenceIcon.className = `presence-icon ${present ? "presence-icon--present" : "presence-icon--absent"}`;
    presenceLabel.textContent = present ? "Person detected" : "No one detected";
    presenceConf.textContent  = `Confidence: ${pct}%`;
    presenceZone.textContent  = p.zone ? p.zone.replace(/_/g, " ") : "";
    confBar.style.width       = `${pct}%`;
    confBar.style.background  = present
      ? `hsl(${120 - (1 - conf) * 60}, 60%, 45%)`
      : "#484f58";
  }

  // ── Vitals ────────────────────────────────────────────────────────────────
  function updateVitals(v, doSlow) {
    if (!v) return;
    breathingRate.textContent = v.breathing_rate > 0 ? v.breathing_rate.toFixed(1) : "--";
    heartRate.textContent     = v.heart_rate     > 0 ? v.heart_rate.toFixed(0)     : "--";
    breathingConf.textContent = `conf: ${(v.breathing_confidence * 100).toFixed(0)}%`;
    heartConf.textContent     = `conf: ${(v.heart_confidence * 100).toFixed(0)}%`;
  }

  // ── Nodes ─────────────────────────────────────────────────────────────────
  function updateNodes(nodes) {
    if (!nodes) return;
    nodesList.innerHTML = Object.entries(nodes).map(([id, n]) => `
      <div class="node-row">
        <span class="node-dot ${n.online ? "node-dot--online" : "node-dot--offline"}"></span>
        <span class="node-id">${id}</span>
        <span class="node-rssi">${n.rssi} dBm</span>
        <span class="node-buf">${n.buffer_fill}/30</span>
      </div>`).join("");
  }

  // ── System stats ──────────────────────────────────────────────────────────
  function updateSystem(d) {
    latencyEl.textContent  = d.inference_latency_ms != null ? `${d.inference_latency_ms.toFixed(1)}ms` : "--";
    infCountEl.textContent = d.inference_count != null ? d.inference_count.toLocaleString() : "--";
    uptimeEl.textContent   = d.uptime_s != null ? formatUptime(d.uptime_s) : "--";

    if (inferenceRate) inferenceRate.textContent = `${d.inference_count || 0} inferences`;
  }

  function formatUptime(s) {
    if (s < 60) return `${Math.round(s)}s`;
    if (s < 3600) return `${Math.floor(s / 60)}m`;
    return `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m`;
  }

  // ── Mini charts ───────────────────────────────────────────────────────────
  function drawLineChart(ctx, data, color, label, min, max) {
    const W = ctx.canvas.offsetWidth || 240;
    const H = ctx.canvas.height;
    ctx.canvas.width = W;

    ctx.clearRect(0, 0, W, H);

    // Background
    ctx.fillStyle = "#0d1117";
    ctx.fillRect(0, 0, W, H);

    // Zero line
    const y0 = H - 4 - ((0 - min) / (max - min)) * (H - 8);
    ctx.strokeStyle = "#30363d";
    ctx.lineWidth   = 0.5;
    ctx.beginPath(); ctx.moveTo(0, y0); ctx.lineTo(W, y0); ctx.stroke();

    // Data line
    ctx.strokeStyle = color;
    ctx.lineWidth   = 1.5;
    ctx.beginPath();
    data.forEach((v, i) => {
      const x = (i / (data.length - 1)) * W;
      const y = H - 4 - ((v - min) / (max - min + 1e-8)) * (H - 8);
      i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
    });
    ctx.stroke();

    // Fill under
    ctx.lineTo(W, H); ctx.lineTo(0, H); ctx.closePath();
    ctx.fillStyle = color.replace(")", ", 0.08)").replace("rgb(", "rgba(").replace("#", "");
    ctx.fill();

    // Label
    if (label) {
      ctx.fillStyle = "#8b949e";
      ctx.font = "9px sans-serif";
      ctx.fillText(label, 4, 11);
    }
  }

  function updateMotionChart(d) {
    // Use inference latency as a proxy for motion energy signal
    const val = d.presence && d.presence.confidence ? d.presence.confidence : 0;
    motionData.push(val);
    if (motionData.length > CHART_LEN) motionData.shift();
    drawLineChart(motionCtx, motionData, "#58a6ff", "presence conf", 0, 1);
  }

  function updateBreathingChart(v) {
    const val = v && v.breathing_rate > 0 ? v.breathing_rate : 0;
    breathingData.push(val);
    if (breathingData.length > CHART_LEN) breathingData.shift();
    drawLineChart(breathCtx, breathingData, "#3fb950", "breaths/min", 0, 30);
  }

  // ── Calibrate button ──────────────────────────────────────────────────────
  calibrateBtn.addEventListener("click", async () => {
    calibrateBtn.disabled = true;
    calibrateBtn.textContent = "Calibrating (keep room empty)...";
    try {
      const res = await fetch("/api/v1/calibrate", { method: "POST" });
      const data = await res.json();
      calibrateBtn.textContent = data.message || "Done";
      setTimeout(() => {
        calibrateBtn.textContent = "Calibrate Room";
        calibrateBtn.disabled = false;
      }, 12000);
    } catch (e) {
      calibrateBtn.textContent = "Error — retry";
      calibrateBtn.disabled = false;
    }
  });
})();
