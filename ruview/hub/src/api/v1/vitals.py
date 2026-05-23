from fastapi import APIRouter, Request
from pydantic import BaseModel

router = APIRouter()


class VitalsResponse(BaseModel):
    breathing_rate: float
    heart_rate: float
    breathing_confidence: float
    heart_confidence: float
    updated_at: float


@router.get("/vitals", response_model=VitalsResponse, summary="Breathing and heart rate")
async def get_vitals(request: Request) -> VitalsResponse:
    state = request.app.state.system_state
    async with state._lock:
        v = state.vitals
    return VitalsResponse(
        breathing_rate=v.breathing_rate,
        heart_rate=v.heart_rate,
        breathing_confidence=v.breathing_confidence,
        heart_confidence=v.heart_confidence,
        updated_at=v.updated_at,
    )
