"""
Inference pipeline runner.

Runs at `inference_rate_hz`, pulls the latest fused window from SystemState,
feeds it through RuVector + VitalsExtractor, and writes results back to state.
"""

import asyncio
import logging
import time

from ..core.config import HubConfig
from ..core.state import SystemState
from .fusion import fuse_nodes, compute_motion_energy
from .ruvector import RuVectorModel
from .vitals import VitalsExtractor

logger = logging.getLogger(__name__)


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
        self._node_weights = [n.weight for n in cfg.nodes]
        self._task: asyncio.Task | None = None
        self._running = False

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
            sleep_time = max(0.0, period - elapsed)
            await asyncio.sleep(sleep_time)

    async def _step(self) -> None:
        window = await self._state.get_fused_window()
        motion = await self._state.get_motion_window()

        if window is None or motion is None:
            return

        # Fuse nodes
        fused = fuse_nodes(window, node_weights=self._node_weights,
                           baseline=self._model._baseline)

        # RuVector inference
        result = self._model.infer(fused)

        # Update vitals extractor
        self._vitals.update(motion)
        vitals = self._vitals.extract()

        # Write presence
        zone = self._estimate_zone(result["joints"]) if result["present"] else ""
        await self._state.update_presence(
            present=result["present"],
            confidence=result["confidence"],
            person_count=1 if result["present"] else 0,
            zone=zone,
        )

        # Write pose
        await self._state.update_pose(
            joints_array=result["joints"],
            confidence=result["confidence"],
        )

        # Write vitals (only meaningful if person is present)
        await self._state.update_vitals(
            breathing_rate=vitals["breathing_rate"],
            heart_rate=vitals["heart_rate"],
            br_conf=vitals["breathing_confidence"],
            hr_conf=vitals["heart_confidence"],
        )

        # Update inference stats
        async with self._state._lock:
            self._state.inference_count += 1
            self._state.inference_latency_ms = result["latency_ms"]

    def _estimate_zone(self, joints) -> str:
        """Very rough zone estimate based on mean hip position."""
        hip_x = (joints[11, 0] + joints[12, 0]) / 2.0
        hip_y = (joints[11, 1] + joints[12, 1]) / 2.0
        col = "left" if hip_x < 0.33 else ("center" if hip_x < 0.66 else "right")
        row = "far" if hip_y > 0.66 else ("middle" if hip_y > 0.33 else "near")
        return f"{row}_{col}"
