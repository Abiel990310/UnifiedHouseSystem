"""
Inference pipeline runner.

Runs at `inference_rate_hz`, pulls the latest fused window from SystemState,
feeds it through RuVector + VitalsExtractor, and writes results back to state.

Presence detection uses a two-layer approach:
  1. Motion-based (works immediately, no training needed) — primary when uncalibrated
  2. RuVector ML model (accurate after training) — primary when calibrated
"""

import asyncio
import logging
import time

import numpy as np

from ..core.config import HubConfig
from ..core.state import SystemState
from .fusion import fuse_nodes, compute_motion_energy
from .ruvector import RuVectorModel
from .vitals import VitalsExtractor

logger = logging.getLogger(__name__)

# Motion variance threshold: CSI amplitude variance above this level
# indicates a person is present. Tuned conservatively — lower = more sensitive.
_MOTION_PRESENCE_THRESHOLD = 8.0
_MOTION_HISTORY_LEN        = 15   # frames to smooth over (~1.5s at 10Hz)


class InferencePipeline:
    def __init__(self, cfg: HubConfig, state: SystemState, model: RuVectorModel) -> None:
        self._cfg    = cfg
        self._state  = state
        self._model  = model
        self._vitals = VitalsExtractor(
            breathing_window  = cfg.vitals.breathing_fft_window,
            heart_window      = cfg.vitals.heart_fft_window,
            breathing_range_hz= tuple(cfg.vitals.breathing_range_hz),
            heart_range_hz    = tuple(cfg.vitals.heart_range_hz),
        )
        self._node_weights  = [n.weight for n in cfg.nodes]
        self._task: asyncio.Task | None = None
        self._running       = False

        # Rolling history of per-node mean motion variance for smoothing
        self._motion_history: list[float] = []
        # Baseline motion level captured during calibration (empty room)
        self._baseline_motion: float = 0.0

    async def start(self) -> None:
        self._running = True
        self._task = asyncio.create_task(self._loop(), name="inference_pipeline")
        logger.info("Inference pipeline started at %dHz", self._cfg.pipeline.inference_rate_hz)

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _loop(self) -> None:
        period = 1.0 / self._cfg.pipeline.inference_rate_hz
        while self._running:
            t_start = time.monotonic()
            try:
                await self._step()
            except Exception as exc:
                logger.error("Inference step error: %s", exc, exc_info=True)
            elapsed = time.monotonic() - t_start
            await asyncio.sleep(max(0.0, period - elapsed))

    async def _step(self) -> None:
        window = await self._state.get_fused_window()
        motion = await self._state.get_motion_window()

        if window is None or motion is None:
            return

        # ── Motion-based presence (works without training) ────────────────
        raw_motion = float(motion.mean())
        self._motion_history.append(raw_motion)
        if len(self._motion_history) > _MOTION_HISTORY_LEN:
            self._motion_history.pop(0)

        smoothed_motion = float(np.mean(self._motion_history))

        # Subtract the empty-room baseline captured during calibration
        motion_above_baseline = max(0.0, smoothed_motion - self._baseline_motion)

        # Map to 0..1 confidence (sigmoid-like curve)
        motion_conf = float(1.0 - np.exp(-motion_above_baseline / _MOTION_PRESENCE_THRESHOLD))

        # ── RuVector ML inference (accurate after training) ───────────────
        fused  = fuse_nodes(window, node_weights=self._node_weights,
                            baseline=self._model._baseline)
        result = self._model.infer(fused)

        # ── Blend: use motion detection until model is properly trained ───
        if self._model._calibrated:
            # Weight: 60% motion + 40% model (motion is more reliable early on)
            blended_conf = 0.6 * motion_conf + 0.4 * result["confidence"]
        else:
            # Model has random weights — trust motion only
            blended_conf = motion_conf

        present = blended_conf >= self._cfg.pipeline.presence_threshold

        logger.debug("motion=%.2f baseline=%.2f above=%.2f conf=%.2f present=%s",
                     smoothed_motion, self._baseline_motion,
                     motion_above_baseline, blended_conf, present)

        # ── Vitals ────────────────────────────────────────────────────────
        self._vitals.update(motion)
        vitals = self._vitals.extract()

        # ── Write state ───────────────────────────────────────────────────
        zone = self._estimate_zone(result["joints"]) if present else ""
        await self._state.update_presence(
            present=present,
            confidence=round(blended_conf, 4),
            person_count=1 if present else 0,
            zone=zone,
        )
        await self._state.update_pose(
            joints_array=result["joints"],
            confidence=blended_conf,
        )
        await self._state.update_vitals(
            breathing_rate=vitals["breathing_rate"],
            heart_rate=vitals["heart_rate"],
            br_conf=vitals["breathing_confidence"],
            hr_conf=vitals["heart_confidence"],
        )

        async with self._state._lock:
            self._state.inference_count += 1
            self._state.inference_latency_ms = result["latency_ms"]

    def set_baseline_motion(self, baseline: float) -> None:
        """Called after calibration with the empty-room mean motion level."""
        self._baseline_motion = baseline
        logger.info("Motion baseline set to %.3f", baseline)

    def _estimate_zone(self, joints) -> str:
        hip_x = (joints[11, 0] + joints[12, 0]) / 2.0
        hip_y = (joints[11, 1] + joints[12, 1]) / 2.0
        col = "left" if hip_x < 0.33 else ("center" if hip_x < 0.66 else "right")
        row = "far"  if hip_y > 0.66 else ("middle" if hip_y > 0.33 else "near")
        return f"{row}_{col}"
