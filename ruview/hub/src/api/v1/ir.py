"""
IR control — publishes MQTT commands to the IR node (AC + room light).
"""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)
router = APIRouter()


class AcCommand(BaseModel):
    power: Optional[str] = None   # "on" | "off"
    mode:  Optional[str] = None   # cool | heat | fan | dry | auto
    temp:  Optional[int] = Field(None, ge=16, le=30)
    fan:   Optional[str] = None   # auto | low | med | high


class LightCommand(BaseModel):
    power: str   # "on" | "off"


@router.post("/ir/ac", summary="Control air conditioner via IR")
async def set_ac(cmd: AcCommand, request: Request) -> dict:
    ir   = request.app.state.ir
    mqtt = request.app.state.mqtt
    try:
        state = await ir.set_ac(
            mqtt,
            power=cmd.power,
            mode=cmd.mode,
            temp=cmd.temp,
            fan=cmd.fan,
        )
    except Exception as exc:
        raise HTTPException(502, f"MQTT publish failed: {exc}") from exc
    return {
        "status": "sent",
        "ac": {"power": state.ac.power, "mode": state.ac.mode,
               "temp": state.ac.temp,  "fan": state.ac.fan},
    }


@router.post("/ir/light", summary="Toggle room light via IR")
async def set_light(cmd: LightCommand, request: Request) -> dict:
    if cmd.power not in ("on", "off"):
        raise HTTPException(400, "power must be 'on' or 'off'")
    ir   = request.app.state.ir
    mqtt = request.app.state.mqtt
    try:
        state = await ir.set_light(mqtt, cmd.power)
    except Exception as exc:
        raise HTTPException(502, f"MQTT publish failed: {exc}") from exc
    return {"status": "sent", "light": {"power": state.light.power}}


@router.get("/ir/status", summary="IR node online status + current AC/light state")
async def get_ir_status(request: Request) -> dict:
    ir = request.app.state.ir
    return {
        "online": ir.state.online,
        "ac": {"power": ir.state.ac.power, "mode": ir.state.ac.mode,
               "temp": ir.state.ac.temp,  "fan": ir.state.ac.fan},
        "light": {"power": ir.state.light.power},
    }
