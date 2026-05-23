import time
import platform
import os
import asyncio
import numpy as np
import logging
from fastapi import APIRouter, Request, BackgroundTasks
from pydantic import BaseModel

router = APIRouter()


class SystemInfo(BaseModel):
    version: str
    uptime_s: float
    inference_count: int
    inference_latency_ms: float
    model_parameters: int
    calibrated: bool
    platform: str
    python_version: str


@router.get("/system", response_model=SystemInfo, summary="Hub system status")
async def get_system_info(request: Request) -> SystemInfo:
    state = request.app.state.system_state
    model = request.app.state.model
    snap  = await state.snapshot()
    return SystemInfo(
        version="1.0.0",
        uptime_s=snap["uptime_s"],
        inference_count=snap["inference_count"],
        inference_latency_ms=snap["inference_latency_ms"],
        model_parameters=model.parameter_count,
        calibrated=model._calibrated,
        platform=platform.platform(),
        python_version=platform.python_version(),
    )


@router.post("/calibrate", summary="Capture empty-room baseline for differential CSI")
async def calibrate(request: Request, background_tasks: BackgroundTasks) -> dict:
    """
    Trigger a 10-second empty-room calibration.
    Make sure the room is completely empty before calling this.
    """
    background_tasks.add_task(_run_calibration, request.app)
    return {"status": "started", "duration_s": 10,
            "message": "Keep room empty for 10 seconds."}


async def _run_calibration(app) -> None:
    log = logging.getLogger("calibrate")

    state    = app.state.system_state
    model    = app.state.model
    pipeline = app.state.pipeline
    cfg      = app.state.config

    log.info("Calibration started — collecting 10s of empty-room CSI")

    csi_samples    = []
    motion_samples = []
    n_steps = cfg.pipeline.inference_rate_hz * 10

    for _ in range(n_steps):
        window = await state.get_fused_window()
        motion = await state.get_motion_window()
        if window is not None:
            csi_samples.append(window.mean(axis=0))
        if motion is not None:
            motion_samples.append(float(motion.mean()))
        await asyncio.sleep(1.0 / cfg.pipeline.inference_rate_hz)

    if not csi_samples:
        log.warning("Calibration failed — no CSI data. Are all nodes connected?")
        return

    # Set CSI baseline on the model (for differential CSI)
    baseline = np.mean(csi_samples, axis=0)
    model.set_baseline(baseline)

    # Set motion baseline on the pipeline (for motion-based presence)
    if motion_samples and pipeline is not None:
        baseline_motion = float(np.mean(motion_samples))
        pipeline.set_baseline_motion(baseline_motion)
        log.info("Motion baseline: %.3f", baseline_motion)

    # Save weights so calibration persists across restarts
    weights_path = os.path.join(
        os.path.dirname(cfg.storage.db_path), "ruvector_weights.npz")
    model.save_weights(weights_path)
    log.info("Calibration complete. Baseline saved to %s", weights_path)
