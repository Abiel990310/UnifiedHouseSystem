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


@router.get("/debug", summary="Raw motion stats for tuning")
async def get_debug(request: Request) -> dict:
    """Shows live motion values — useful for checking calibration quality."""
    pipeline = request.app.state.pipeline
    return pipeline.debug if pipeline else {}


@router.post("/calibrate", summary="Capture empty-room baseline")
async def calibrate(request: Request, background_tasks: BackgroundTasks) -> dict:
    background_tasks.add_task(_run_calibration, request.app)
    return {"status": "started", "duration_s": 15,
            "message": "Keep room empty for 15 seconds."}


async def _run_calibration(app) -> None:
    log = logging.getLogger("calibrate")

    state    = app.state.system_state
    model    = app.state.model
    pipeline = app.state.pipeline
    cfg      = app.state.config

    log.info("Calibration started — 15s empty-room capture")

    csi_samples    = []
    motion_samples = []
    n_steps = cfg.pipeline.inference_rate_hz * 15   # 15 seconds

    for _ in range(n_steps):
        window = await state.get_fused_window()
        motion = await state.get_motion_window()
        if window is not None:
            csi_samples.append(window.mean(axis=0))
        if motion is not None:
            # Max across nodes — same metric used in runner
            motion_samples.append(float(motion.mean(axis=0).max()))
        await asyncio.sleep(1.0 / cfg.pipeline.inference_rate_hz)

    if not motion_samples:
        log.warning("Calibration failed — no motion data. Are nodes connected?")
        return

    motion_arr = np.array(motion_samples, dtype=np.float32)
    mean_val   = float(motion_arr.mean())
    std_val    = float(motion_arr.std())

    log.info("Calibration result  mean=%.2f  std=%.2f  samples=%d",
             mean_val, std_val, len(motion_samples))

    # Set motion baseline on pipeline
    if pipeline is not None:
        pipeline.set_baseline_motion(mean_val, std_val)

    # Set CSI baseline on model
    if csi_samples:
        baseline = np.mean(csi_samples, axis=0)
        model.set_baseline(baseline)

    # Save so calibration survives restart
    weights_path = os.path.join(
        os.path.dirname(cfg.storage.db_path), "ruvector_weights.npz")
    os.makedirs(os.path.dirname(weights_path), exist_ok=True)

    # Save calibration data alongside model weights
    extra_path = os.path.join(os.path.dirname(cfg.storage.db_path), "calibration.npz")
    np.savez(extra_path,
             baseline_mean=np.array(mean_val),
             baseline_std=np.array(std_val))
    model.save_weights(weights_path)

    log.info("Calibration saved. Enter threshold: %.2f (%.1f + %.1f×2.5)",
             mean_val + 2.5 * std_val, mean_val, std_val)
