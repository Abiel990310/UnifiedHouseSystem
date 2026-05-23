import time
from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel

router = APIRouter()


class NodeInfo(BaseModel):
    node_id: str
    online: bool
    rssi: int
    last_seen: float
    last_seen_ago_s: float
    frames_received: int
    buffer_fill: int
    csi_active: bool


@router.get("/nodes", summary="Status of all sensor nodes")
async def list_nodes(request: Request) -> list[NodeInfo]:
    state = request.app.state.system_state
    now = time.time()
    async with state._lock:
        return [
            NodeInfo(
                node_id=n.node_id,
                online=n.online and (now - n.last_seen < 30),
                rssi=n.rssi,
                last_seen=n.last_seen,
                last_seen_ago_s=round(now - n.last_seen, 1),
                frames_received=n.frames_received,
                buffer_fill=len(n.amp_buffer),
                csi_active=n.csi_active,
            )
            for n in state.nodes.values()
        ]


@router.get("/nodes/{node_id}", summary="Status of a specific sensor node")
async def get_node(node_id: str, request: Request) -> NodeInfo:
    state = request.app.state.system_state
    now = time.time()
    async with state._lock:
        n = state.nodes.get(node_id)
        if n is None:
            raise HTTPException(status_code=404, detail=f"Node {node_id!r} not found")
        return NodeInfo(
            node_id=n.node_id,
            online=n.online and (now - n.last_seen < 30),
            rssi=n.rssi,
            last_seen=n.last_seen,
            last_seen_ago_s=round(now - n.last_seen, 1),
            frames_received=n.frames_received,
            buffer_fill=len(n.amp_buffer),
            csi_active=n.csi_active,
        )
