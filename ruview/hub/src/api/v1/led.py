"""
LED node control — publishes MQTT commands to ESP32-S3 LED nodes.
"""

import json
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from ...mqtt.topics import Topics

logger = logging.getLogger(__name__)
router = APIRouter()

VALID_PRESETS = {
    "off", "chill", "focus", "sleep", "party", "sunset", "ocean", "custom",
    "aurora", "fire", "candle", "zen", "neon", "midnight", "rose", "galaxy",
    "morning", "disco",
}


class LedCommand(BaseModel):
    target:     str           = "all"    # "all" | "led_1" | "led_2" | "led_3"
    preset:     Optional[str] = None
    r:          Optional[int] = Field(None, ge=0, le=255)
    g:          Optional[int] = Field(None, ge=0, le=255)
    b:          Optional[int] = Field(None, ge=0, le=255)
    brightness: Optional[int] = Field(None, ge=0, le=250)


@router.post("/led/set", summary="Set LED preset or color")
async def set_led(cmd: LedCommand, request: Request) -> dict:
    if cmd.preset and cmd.preset not in VALID_PRESETS:
        raise HTTPException(400, f"Unknown preset '{cmd.preset}'. Valid: {sorted(VALID_PRESETS)}")

    payload: dict = {}
    if cmd.preset     is not None: payload["preset"]     = cmd.preset
    if cmd.r          is not None: payload["r"]          = cmd.r
    if cmd.g          is not None: payload["g"]          = cmd.g
    if cmd.b          is not None: payload["b"]          = cmd.b
    if cmd.brightness is not None: payload["brightness"] = cmd.brightness

    if not payload:
        raise HTTPException(400, "No fields provided")

    mqtt  = request.app.state.mqtt
    topic = Topics.LED_ALL if cmd.target == "all" else Topics.led_set(cmd.target)

    try:
        await mqtt.publish(topic, json.dumps(payload))
    except Exception as exc:
        raise HTTPException(502, f"MQTT publish failed: {exc}") from exc

    logger.info("LED → %s  %s", topic, payload)
    return {"status": "sent", "topic": topic, "payload": payload}


@router.get("/led/nodes", summary="LED node online status")
async def get_led_nodes(request: Request) -> dict:
    return request.app.state.mqtt.led_nodes
