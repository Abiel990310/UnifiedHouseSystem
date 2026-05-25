"""
IR control — proxies AC and room-light commands to the IR ESP32 node.
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
    ir = request.app.state.ir
    try:
        state = await ir.set_ac(
            power=cmd.power,
            mode=cmd.mode,
            temp=cmd.temp,
            fan=cmd.fan,
        )
    except RuntimeError as exc:
        raise HTTPException(502, str(exc)) from exc
    return {
        "status": "sent",
        "ac": {
            "power": state.ac.power,
            "mode":  state.ac.mode,
            "temp":  state.ac.temp,
            "fan":   state.ac.fan,
        },
    }


@router.post("/ir/light", summary="Toggle room light via IR")
async def set_light(cmd: LightCommand, request: Request) -> dict:
    if cmd.power not in ("on", "off"):
        raise HTTPException(400, "power must be 'on' or 'off'")
    ir = request.app.state.ir
    try:
        state = await ir.set_light(cmd.power)
    except RuntimeError as exc:
        raise HTTPException(502, str(exc)) from exc
    return {"status": "sent", "light": {"power": state.light.power}}


@router.get("/ir/status", summary="IR node + current AC/light state")
async def get_ir_status(request: Request) -> dict:
    ir = request.app.state.ir
    data = await ir.get_status()
    return {
        "online": ir.online,
        "ac": {
            "power": ir.state.ac.power,
            "mode":  ir.state.ac.mode,
            "temp":  ir.state.ac.temp,
            "fan":   ir.state.ac.fan,
        },
        "light": {"power": ir.state.light.power},
        **data,
    }
