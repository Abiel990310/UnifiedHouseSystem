"""
WebSocket endpoint — streams full system state snapshot at 10Hz.

All connected browser clients receive the same JSON broadcast.
"""

import asyncio
import json
import logging
import time

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

ws_router = APIRouter()


class ConnectionManager:
    def __init__(self) -> None:
        self._clients: list[WebSocket] = []

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._clients.append(ws)
        logger.info("WebSocket client connected (%d total)", len(self._clients))

    def disconnect(self, ws: WebSocket) -> None:
        if ws in self._clients:
            self._clients.remove(ws)
        logger.info("WebSocket client disconnected (%d remaining)", len(self._clients))

    async def broadcast(self, data: str) -> None:
        dead = []
        for client in self._clients:
            try:
                await client.send_text(data)
            except Exception:
                dead.append(client)
        for c in dead:
            self.disconnect(c)

    @property
    def client_count(self) -> int:
        return len(self._clients)


manager = ConnectionManager()


@ws_router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    await manager.connect(websocket)
    state  = websocket.app.state.system_state
    period = 0.1  # 10Hz

    try:
        while True:
            t_start = time.monotonic()
            snapshot = await state.snapshot()
            await websocket.send_text(json.dumps(snapshot, default=str))
            elapsed = time.monotonic() - t_start
            await asyncio.sleep(max(0.0, period - elapsed))
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as exc:
        logger.error("WebSocket error: %s", exc)
        manager.disconnect(websocket)
