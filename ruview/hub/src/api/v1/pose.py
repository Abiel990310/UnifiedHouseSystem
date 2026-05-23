from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/pose", summary="17-joint skeleton pose estimation")
async def get_pose(request: Request) -> dict:
    state = request.app.state.system_state
    async with state._lock:
        return state.pose.to_dict()
