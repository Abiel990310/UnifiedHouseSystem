"""
RuView Hub — FastAPI application entry point.

Startup order:
  1. Load config
  2. Set up logging
  3. Open database
  4. Load RuVector model
  5. Create SystemState
  6. Start MQTT client
  7. Start inference pipeline
  8. Mount API routes + WebSocket
  9. Serve static dashboard
"""

import asyncio
import logging
import os
import sys
import time

from contextlib import asynccontextmanager

import numpy as np
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from .core.config import load_config
from .core.state import SystemState
from .core.logger import setup_logging
from .ir_proxy import IrController
from .mqtt.client import MqttClient
from .pipeline.ruvector import RuVectorModel
from .pipeline.runner import InferencePipeline
from .storage.db import Database
from .api.v1.router import v1_router
from .api.websocket import ws_router

logger = logging.getLogger(__name__)

# ── Locate config relative to this file ───────────────────────────────────────

_SRC_DIR      = os.path.dirname(os.path.abspath(__file__))
_HUB_DIR      = os.path.dirname(_SRC_DIR)
_DASHBOARD_DIR = os.path.join(os.path.dirname(_HUB_DIR), "dashboard")


# ── Lifespan ───────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ──────────────────────────────────────────────────────────────
    cfg = load_config(_HUB_DIR)
    setup_logging(cfg.logging.level, cfg.logging.file)
    logger.info("RuView Hub starting (Python %s)", sys.version.split()[0])

    node_ids = [n.id for n in cfg.nodes]

    # Database
    db = Database(cfg.storage.db_path, cfg.storage.history_days)
    await db.start()
    await db.log_event("hub", "startup")

    # System state
    state = SystemState(node_ids=node_ids, window_size=cfg.pipeline.window_size)

    # RuVector model
    weights_path = os.path.join(os.path.dirname(cfg.storage.db_path), "ruvector_weights.npz")
    model = RuVectorModel(weights_path=weights_path)
    logger.info("RuVector model loaded (%d parameters)", model.parameter_count)

    # MQTT client
    mqtt = MqttClient(cfg.mqtt, state)
    await mqtt.start()

    # Inference pipeline
    pipeline = InferencePipeline(cfg, state, model)
    await pipeline.start()

    # Restore calibration baseline if saved
    calib_path = os.path.join(os.path.dirname(cfg.storage.db_path), "calibration.npz")
    if os.path.exists(calib_path):
        try:
            calib = np.load(calib_path)
            pipeline.set_baseline_motion(
                float(calib["baseline_mean"]),
                float(calib["baseline_std"]),
            )
            logger.info("Calibration restored from %s", calib_path)
        except Exception as exc:
            logger.warning("Could not restore calibration: %s", exc)

    # Periodic DB logging (every 5 seconds)
    async def _db_logger():
        while True:
            await asyncio.sleep(5)
            try:
                async with state._lock:
                    p = state.presence
                    v = state.vitals
                await db.log_presence(p.present, p.confidence, p.zone)
                await db.log_vitals(v.breathing_rate, v.heart_rate,
                                    v.breathing_confidence, v.heart_confidence)
            except Exception as exc:
                logger.error("DB logging error: %s", exc)

    # Periodic DB purge (every 6 hours)
    async def _db_purge():
        while True:
            await asyncio.sleep(6 * 3600)
            await db.purge_old_records()

    db_log_task   = asyncio.create_task(_db_logger(), name="db_logger")
    db_purge_task = asyncio.create_task(_db_purge(),  name="db_purge")

    # IR controller (publishes MQTT commands, no IP needed)
    ir = IrController(node_id=cfg.ir.node_id)
    mqtt._ir_controller = ir   # wire up so MQTT heartbeats update IR state

    # Attach to app state so routes can access them
    app.state.config       = cfg
    app.state.system_state = state
    app.state.model        = model
    app.state.pipeline     = pipeline
    app.state.db           = db
    app.state.ir           = ir

    logger.info("RuView Hub ready on http://%s:%d", cfg.api.host, cfg.api.port)
    yield

    # ── Shutdown ─────────────────────────────────────────────────────────────
    logger.info("RuView Hub shutting down...")
    db_log_task.cancel()
    db_purge_task.cancel()
    await pipeline.stop()
    await mqtt.stop()
    await db.log_event("hub", "shutdown")
    await db.stop()
    logger.info("RuView Hub stopped.")


# ── Application ────────────────────────────────────────────────────────────────

def create_app() -> FastAPI:
    app = FastAPI(
        title="RuView Hub API",
        description="WiFi CSI person tracking — presence, pose, and vitals.",
        version="1.0.0",
        lifespan=lifespan,
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
    )

    app.include_router(v1_router)
    app.include_router(ws_router)

    # Serve web dashboard
    if os.path.isdir(_DASHBOARD_DIR):
        app.mount("/static", StaticFiles(directory=_DASHBOARD_DIR), name="static")

        @app.get("/", include_in_schema=False)
        async def dashboard():
            return FileResponse(os.path.join(_DASHBOARD_DIR, "index.html"))

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn
    cfg = load_config(_HUB_DIR)
    uvicorn.run(
        "ruview.hub.src.main:app",
        host=cfg.api.host,
        port=cfg.api.port,
        reload=False,
        log_level=cfg.logging.level.lower(),
    )
