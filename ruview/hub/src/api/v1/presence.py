from fastapi import APIRouter, Request
from pydantic import BaseModel

router = APIRouter()


class PresenceResponse(BaseModel):
    present: bool
    confidence: float
    person_count: int
    zone: str
    updated_at: float


@router.get("/presence", response_model=PresenceResponse, summary="Current presence status")
async def get_presence(request: Request) -> PresenceResponse:
    state = request.app.state.system_state
    async with state._lock:
        p = state.presence
    return PresenceResponse(
        present=p.present,
        confidence=round(p.confidence, 4),
        person_count=p.person_count,
        zone=p.zone,
        updated_at=p.updated_at,
    )
