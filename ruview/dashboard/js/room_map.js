/**
 * 2D room visualization on <canvas id="room-canvas">.
 *
 * Draws:
 *  - Room outline
 *  - Node positions (triangles in corners)
 *  - Heat map overlay (motion energy)
 *  - 17-joint skeleton when person is present
 */

(function () {
  const canvas = document.getElementById("room-canvas");
  const ctx    = canvas.getContext("2d");

  // Node positions — adjust to match your physical placement (0..1 normalized)
  const NODE_POSITIONS = {
    node_1: { x: 0.05, y: 0.05, label: "N1" },
    node_2: { x: 0.95, y: 0.05, label: "N2" },
    node_3: { x: 0.50, y: 0.97, label: "N3" },
  };

  // COCO skeleton connections
  const SKELETON = [
    [0,1],[0,2],[1,3],[2,4],           // head
    [5,6],[5,7],[7,9],[6,8],[8,10],    // arms
    [5,11],[6,12],[11,12],             // torso
    [11,13],[13,15],[12,14],[14,16],   // legs
  ];

  const JOINT_COLORS = [
    "#ff6b6b","#ff6b6b","#ff6b6b","#ffd93d","#ffd93d",   // head
    "#6bcb77","#6bcb77","#6bcb77","#6bcb77","#6bcb77","#6bcb77",  // arms
    "#4d96ff","#4d96ff",                                  // hips
    "#4d96ff","#4d96ff","#4d96ff","#4d96ff",             // legs
  ];

  let _state = null;
  let _motionHistory = new Array(20).fill(0);

  function resize() {
    const container = canvas.parentElement;
    const size = Math.min(container.clientWidth - 16, container.clientHeight - 16, 520);
    canvas.width  = size;
    canvas.height = size * 0.75;
    if (_state) draw(_state);
  }

  function worldToCanvas(nx, ny) {
    return {
      x: 20 + nx * (canvas.width  - 40),
      y: 20 + ny * (canvas.height - 40),
    };
  }

  function draw(state) {
    const W = canvas.width;
    const H = canvas.height;
    ctx.clearRect(0, 0, W, H);

    // Room background
    ctx.fillStyle = "#0a0e13";
    ctx.fillRect(0, 0, W, H);

    // Room border
    ctx.strokeStyle = "#30363d";
    ctx.lineWidth = 2;
    ctx.strokeRect(20, 20, W - 40, H - 40);

    // Grid lines (subtle)
    ctx.strokeStyle = "#1c2128";
    ctx.lineWidth = 0.5;
    for (let i = 1; i < 3; i++) {
      const x = 20 + (W - 40) * i / 3;
      ctx.beginPath(); ctx.moveTo(x, 20); ctx.lineTo(x, H - 20); ctx.stroke();
    }
    for (let j = 1; j < 3; j++) {
      const y = 20 + (H - 40) * j / 3;
      ctx.beginPath(); ctx.moveTo(20, y); ctx.lineTo(W - 20, y); ctx.stroke();
    }

    // Motion heat overlay
    const presence = state.presence || {};
    const motionEnergy = _motionHistory.reduce((a, b) => a + b, 0) / _motionHistory.length;
    if (presence.present && motionEnergy > 0.01) {
      const joints = state.pose && state.pose.joints;
      if (joints) {
        const hipL = joints["left_hip"];
        const hipR = joints["right_hip"];
        if (hipL && hipR) {
          const cx = (hipL.x + hipR.x) / 2;
          const cy = (hipL.y + hipR.y) / 2;
          const cp = worldToCanvas(cx, cy);
          const r  = Math.min(W, H) * 0.18;
          const grad = ctx.createRadialGradient(cp.x, cp.y, 0, cp.x, cp.y, r);
          const alpha = Math.min(motionEnergy * 2, 0.35);
          grad.addColorStop(0,   `rgba(88, 166, 255, ${alpha})`);
          grad.addColorStop(1,   "rgba(88, 166, 255, 0)");
          ctx.fillStyle = grad;
          ctx.beginPath();
          ctx.arc(cp.x, cp.y, r, 0, Math.PI * 2);
          ctx.fill();
        }
      }
    }

    // Sensor nodes
    const nodes = state.nodes || {};
    Object.entries(NODE_POSITIONS).forEach(([id, pos]) => {
      const nodeInfo = nodes[id];
      const online   = nodeInfo && nodeInfo.online;
      const cp = worldToCanvas(pos.x, pos.y);

      // Triangle marker
      ctx.save();
      ctx.translate(cp.x, cp.y);
      ctx.beginPath();
      ctx.moveTo(0, -8); ctx.lineTo(7, 6); ctx.lineTo(-7, 6);
      ctx.closePath();
      ctx.fillStyle = online ? "#3fb950" : "#484f58";
      ctx.fill();
      ctx.restore();

      // Label
      ctx.fillStyle = online ? "#3fb950" : "#8b949e";
      ctx.font = "9px sans-serif";
      ctx.textAlign = "center";
      ctx.fillText(pos.label, cp.x, cp.y + 18);
    });

    // Skeleton
    if (presence.present && state.pose) {
      drawSkeleton(state.pose);
    }
  }

  function drawSkeleton(poseState) {
    const joints = poseState.joints;
    if (!joints) return;

    const JOINT_NAMES = [
      "nose","left_eye","right_eye","left_ear","right_ear",
      "left_shoulder","right_shoulder","left_elbow","right_elbow",
      "left_wrist","right_wrist","left_hip","right_hip",
      "left_knee","right_knee","left_ankle","right_ankle",
    ];

    // Draw bones
    ctx.strokeStyle = "rgba(88,166,255,0.6)";
    ctx.lineWidth   = 2;
    SKELETON.forEach(([a, b]) => {
      const jA = joints[JOINT_NAMES[a]];
      const jB = joints[JOINT_NAMES[b]];
      if (!jA || !jB) return;
      if (jA.confidence < 0.2 || jB.confidence < 0.2) return;
      const pA = worldToCanvas(jA.x, jA.y);
      const pB = worldToCanvas(jB.x, jB.y);
      ctx.beginPath();
      ctx.moveTo(pA.x, pA.y);
      ctx.lineTo(pB.x, pB.y);
      ctx.stroke();
    });

    // Draw joints
    JOINT_NAMES.forEach((name, i) => {
      const j = joints[name];
      if (!j || j.confidence < 0.2) return;
      const p = worldToCanvas(j.x, j.y);
      ctx.beginPath();
      ctx.arc(p.x, p.y, 4, 0, Math.PI * 2);
      ctx.fillStyle = JOINT_COLORS[i];
      ctx.fill();
    });
  }

  // Update on ruview-update event
  window.addEventListener("ruview-update", (evt) => {
    _state = evt.detail;

    // Feed motion history from motion variance proxy
    const nodes = _state.nodes || {};
    const mvs = Object.values(nodes).map(n => 0);  // placeholder
    const energy = mvs.length > 0 ? mvs.reduce((a, b) => a + b, 0) / mvs.length : 0;
    _motionHistory.push(energy);
    if (_motionHistory.length > 20) _motionHistory.shift();

    draw(_state);
  });

  // Responsive resize
  window.addEventListener("resize", resize);
  setTimeout(resize, 50);
})();
