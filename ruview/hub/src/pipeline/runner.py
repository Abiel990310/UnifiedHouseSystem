"""
Inference pipeline runner — adaptive statistical presence detection.

Uses z-score detection: presence threshold automatically adapts to
the room's ambient WiFi noise floor captured during calibration.
No manual sensitivity tuning needed.
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
# How many standard deviations above baseline = "person present"
# Higher = less sensitive (fewer false positives)
# Lower  = more sensitive (detects stillness better)
_Z_ENTER = 2.5   # z-score to trigger presence
_Z_EXIT  = 1.0   # z-score to drop back to absent (hysteresis)
_HOLD_SECONDS = 4.0   # stay present N seconds after last motion spike
_EMA_ALPHA    = 0.25  # smoothing (0.1=very smooth, 0.5=faster response)


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

        # ── Adaptive detection state ──────────────────────────────────────
        self._ema_motion: float       = 0.0
        self._baseline_mean: float    = 0.0
        self._baseline_std: float     = 1.0   # populated during calibration
        self._calibrated: bool        = False
        self._currently_present: bool = False
        self._last_motion_time: float = 0.0

        # Debug stats exposed via API
        self.debug: dict = {
            "raw_motion": 0.0,
            "ema_motion": 0.0,
            "z_score":    0.0,
            "baseline_mean": 0.0,
            "baseline_std":  1.0,
            "calibrated":    False,
        }

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

        # ── Motion: max across nodes (if any node sees you, you're there) ──
        per_node   = motion.mean(axis=0)      # [n_nodes]
        raw_motion = float(per_node.max())

        # ── Exponential moving average ─────────────────────────────────────
        self._ema_motion = (_EMA_ALPHA * raw_motion
                            + (1.0 - _EMA_ALPHA) * self._ema_motion)

        # ── Z-score: how many std devs above empty-room baseline? ──────────
        z = (self._ema_motion - self._baseline_mean) / (self._baseline_std + 1e-6)

        # Map z-score to 0..1 confidence using sigmoid centered at _Z_ENTER
        motion_conf = float(1.0 / (1.0 + math.exp(-(z - _Z_ENTER) * 1.5)))

        # ── Hysteresis + hold timer ────────────────────────────────────────
        now = time.monotonic()
        if z >= _Z_ENTER:
            self._last_motion_time = now

        if not self._currently_present:
            if z >= _Z_ENTER:
                self._currently_present = True
                logger.info("PRESENT  z=%.2f  ema=%.1f  mean=%.1f  std=%.1f",
                            z, self._ema_motion, self._baseline_mean, self._baseline_std)
        else:
            hold_expired = (now - self._last_motion_time) > _HOLD_SECONDS
            if z < _Z_EXIT and hold_expired:
                self._currently_present = False
                logger.info("ABSENT   z=%.2f  ema=%.1f", z, self._ema_motion)

        # ── Update debug stats ─────────────────────────────────────────────
        self.debug.update({
            "raw_motion":    round(raw_motion, 2),
            "ema_motion":    round(self._ema_motion, 2),
            "z_score":       round(z, 3),
            "baseline_mean": round(self._baseline_mean, 2),
            "baseline_std":  round(self._baseline_std, 2),
            "calibrated":    self._calibrated,
        })

        # ── RuVector ML (pose / vitals) ────────────────────────────────────
        fused  = fuse_nodes(window, node_weights=self._node_weights,
                            baseline=self._model._baseline)
        result = self._model.infer(fused)

        self._vitals.update(motion)
        vitals = self._vitals.extract()

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

    def set_baseline_motion(self, mean: float, std: float) -> None:
        """Called after calibration with empty-room motion statistics."""
        self._baseline_mean    = mean
        self._baseline_std     = max(std, 0.5)   # floor to avoid division issues
        self._ema_motion       = mean             # reset EMA to baseline
        self._calibrated       = True
        self._currently_present = False
        logger.info("Baseline set  mean=%.2f  std=%.2f  enter_threshold=%.2f",
                    mean, std, mean + _Z_ENTER * std)

    def _estimate_zone(self, joints) -> str:
        hip_x = (joints[11, 0] + joints[12, 0]) / 2.0
        hip_y = (joints[11, 1] + joints[12, 1]) / 2.0
        col = "left"   if hip_x < 0.33 else ("center" if hip_x < 0.66 else "right")
        row = "far"    if hip_y > 0.66 else ("middle"  if hip_y > 0.33 else "near")
        return f"{row}_{col}"
