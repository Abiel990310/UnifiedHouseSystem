"""
Inference pipeline runner — stable motion-based presence detection.

Detection uses three layers of stability:
  1. Exponential moving average smoothing (removes flicker)
  2. Hysteresis (different thresholds to enter vs exit "present" state)
  3. Hold timer (stays "present" for N seconds after last motion spike)
"""

import asyncio
import logging
import time
import math

import numpy as np

from ..core.config import HubConfig
from ..core.state import SystemState
from .fusion import fuse_nodes
from .ruvector import RuVectorModel
from .vitals import VitalsExtractor

logger = logging.getLogger(__name__)

# ── Detection tuning ──────────────────────────────────────────────────────────
# Confidence to trigger "person present" (entering from absent state)
_ENTER_THRESHOLD = 0.45
# Confidence to drop back to "absent" (must be lower than enter — hysteresis)
_EXIT_THRESHOLD  = 0.20
# Stay "present" for at least this many seconds after last motion spike
_HOLD_SECONDS    = 4.0
# Exponential moving average alpha: 0.2 = very smooth, 0.5 = faster response
_EMA_ALPHA       = 0.25
# How hard it is to trigger — increase if too sensitive, decrease if misses you
_SENSITIVITY     = 6.0


class InferencePipeline:
    def __init__(self, cfg: HubConfig, state: SystemState, model: RuVectorModel) -> None:
        self._cfg    = cfg
        self._state  = state
        self._model  = model
        self._vitals = VitalsExtractor(
            breathing_window   = cfg.vitals.breathing_fft_window,
            heart_window       = cfg.vitals.heart_fft_window,
            breathing_range_hz = tuple(cfg.vitals.breathing_range_hz),
            heart_range_hz     = tuple(cfg.vitals.heart_range_hz),
        )
        self._node_weights = [n.weight for n in cfg.nodes]
        self._task: asyncio.Task | None = None
        self._running = False

        # ── Stable detection state ────────────────────────────────────────
        self._ema_motion: float        = 0.0   # smoothed motion level
        self._baseline_motion: float   = 0.0   # empty-room baseline
        self._currently_present: bool  = False  # hysteresis state
        self._last_motion_time: float  = 0.0   # last time motion was high
        self._confidence: float        = 0.0   # last published confidence

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
            await asyncio.sleep(max(0.0, period - (time.monotonic() - t_start)))

    async def _step(self) -> None:
        window = await self._state.get_fused_window()
        motion = await self._state.get_motion_window()
        if window is None or motion is None:
            return

        # ── Motion signal: use MAX across nodes ───────────────────────────
        # If ANY node sees you, you're present. Max is more sensitive than mean.
        per_node = motion.mean(axis=0)          # [n_nodes] — mean over time window
        raw_motion = float(per_node.max())      # most active node wins

        # ── Exponential moving average (smooths out flicker) ──────────────
        self._ema_motion = (_EMA_ALPHA * raw_motion
                            + (1.0 - _EMA_ALPHA) * self._ema_motion)

        # ── Subtract empty-room baseline ──────────────────────────────────
        above = max(0.0, self._ema_motion - self._baseline_motion)

        # ── Map to 0..1 confidence ─────────────────────────────────────────
        motion_conf = 1.0 - math.exp(-above / max(_SENSITIVITY, 0.1))

        # ── Hysteresis + hold timer ────────────────────────────────────────
        now = time.monotonic()

        if motion_conf >= _ENTER_THRESHOLD:
            self._last_motion_time = now  # reset hold timer on each spike

        if not self._currently_present:
            if motion_conf >= _ENTER_THRESHOLD:
                self._currently_present = True
                logger.info("PRESENCE: detected (conf=%.2f  motion=%.1f  baseline=%.1f)",
                            motion_conf, self._ema_motion, self._baseline_motion)
        else:
            # Stay present until BOTH confidence drops AND hold timer expires
            hold_expired = (now - self._last_motion_time) > _HOLD_SECONDS
            if motion_conf < _EXIT_THRESHOLD and hold_expired:
                self._currently_present = False
                logger.info("PRESENCE: left room (conf=%.2f)", motion_conf)

        self._confidence = motion_conf

        # ── RuVector ML inference (for pose / vitals) ─────────────────────
        fused  = fuse_nodes(window, node_weights=self._node_weights,
                            baseline=self._model._baseline)
        result = self._model.infer(fused)

        # ── Vitals ────────────────────────────────────────────────────────
        self._vitals.update(motion)
        vitals = self._vitals.extract()

        # ── Write state ───────────────────────────────────────────────────
        zone = self._estimate_zone(result["joints"]) if self._currently_present else ""
        await self._state.update_presence(
            present      = self._currently_present,
            confidence   = round(motion_conf, 4),
            person_count = 1 if self._currently_present else 0,
            zone         = zone,
        )
        await self._state.update_pose(
            joints_array = result["joints"],
            confidence   = motion_conf if self._currently_present else 0.0,
        )
        await self._state.update_vitals(
            breathing_rate = vitals["breathing_rate"],
            heart_rate     = vitals["heart_rate"],
            br_conf        = vitals["breathing_confidence"],
            hr_conf        = vitals["heart_confidence"],
        )
        async with self._state._lock:
            self._state.inference_count     += 1
            self._state.inference_latency_ms = result["latency_ms"]

    def set_baseline_motion(self, baseline: float) -> None:
        self._baseline_motion   = baseline
        self._ema_motion        = baseline   # reset EMA to baseline level
        self._currently_present = False
        logger.info("Motion baseline set: %.3f — detection ready", baseline)

    def _estimate_zone(self, joints) -> str:
        hip_x = (joints[11, 0] + joints[12, 0]) / 2.0
        hip_y = (joints[11, 1] + joints[12, 1]) / 2.0
        col = "left"   if hip_x < 0.33 else ("center" if hip_x < 0.66 else "right")
        row = "far"    if hip_y > 0.66 else ("middle"  if hip_y > 0.33 else "near")
        return f"{row}_{col}"
