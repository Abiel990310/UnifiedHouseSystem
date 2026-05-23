import time
import platform
import os
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
    Make sure the room is empty before calling this endpoint.
    """
    background_tasks.add_task(_run_calibration, request.app)
    return {"status": "started", "duration_s": 10,
            "message": "Keep room empty for 10 seconds."}


async def _run_calibration(app) -> None:
    import asyncio
    import numpy as np
    import logging
    log = logging.getLogger("calibrate")

    state = app.state.system_state
    model = app.state.model
    cfg   = app.state.config

    log.info("Calibration started — collecting 10s of empty-room CSI")

    samples = []
    for _ in range(cfg.pipeline.inference_rate_hz * 10):
        window = await state.get_fused_window()
        if window is not None:
            samples.append(window.mean(axis=0))
        await asyncio.sleep(1.0 / cfg.pipeline.inference_rate_hz)

    if samples:
        baseline = np.mean(samples, axis=0)
        model.set_baseline(baseline)
        weights_path = os.path.join(
            os.path.dirname(cfg.storage.db_path), "ruvector_weights.npz")
        model.save_weights(weights_path)
        log.info("Calibration complete. Baseline saved.")
    else:
        log.warning("Calibration failed — no CSI data available")
