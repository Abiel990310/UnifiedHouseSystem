"""
Async MQTT subscriber that feeds incoming CSI frames into SystemState.
"""

import asyncio
import json
import logging
import time

import aiomqtt

from ..core.config import MqttConfig
from ..core.state import SystemState
from .topics import Topics

logger = logging.getLogger(__name__)


class MqttClient:
    def __init__(self, cfg: MqttConfig, state: SystemState) -> None:
        self._cfg   = cfg
        self._state = state
        self._task: asyncio.Task | None = None
        self._running = False

    async def start(self) -> None:
        self._running = True
        self._task = asyncio.create_task(self._run(), name="mqtt_client")
        logger.info("MQTT client started → %s:%d", self._cfg.host, self._cfg.port)

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("MQTT client stopped")

    async def _run(self) -> None:
        reconnect_delay = 2
        while self._running:
            try:
                async with aiomqtt.Client(
                    hostname=self._cfg.host,
                    port=self._cfg.port,
                    identifier=self._cfg.client_id,
                    keepalive=self._cfg.keepalive,
                ) as client:
                    reconnect_delay = 2  # reset on success
                    logger.info("Connected to MQTT broker")

                    await client.subscribe(Topics.NODE_CSI,    qos=0)
                    await client.subscribe(Topics.NODE_STATUS, qos=1)
                    logger.info("Subscribed to %s and %s", Topics.NODE_CSI, Topics.NODE_STATUS)

                    async for message in client.messages:
                        if not self._running:
                            break
                        await self._dispatch(str(message.topic), message.payload)

            except aiomqtt.MqttError as exc:
                if not self._running:
                    break
                logger.warning("MQTT disconnected (%s). Reconnecting in %ds...", exc, reconnect_delay)
                await asyncio.sleep(reconnect_delay)
                reconnect_delay = min(reconnect_delay * 2, 60)

    async def _dispatch(self, topic: str, payload: bytes) -> None:
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            logger.debug("Invalid JSON on topic %s", topic)
            return

        node_id = Topics.node_id_from_topic(topic)

        if topic.endswith("/csi"):
            await self._handle_csi(node_id, data)
        elif topic.endswith("/status"):
            await self._handle_status(node_id, data)

    async def _handle_csi(self, node_id: str, data: dict) -> None:
        amp     = data.get("a", [])
        phase   = data.get("p", [])
        motion  = float(data.get("mv", 0.0))
        rssi    = int(data.get("r", -127))
        channel = int(data.get("ch", 0))

        if len(amp) != 56 or len(phase) != 56:
            logger.debug("Malformed CSI from %s: amp=%d phase=%d", node_id, len(amp), len(phase))
            return

        await self._state.update_node_csi(
            node_id=node_id,
            amplitude=amp,
            phase=phase,
            motion_variance=motion,
            rssi=rssi,
            channel=channel,
        )

    async def _handle_status(self, node_id: str, data: dict) -> None:
        await self._state.update_node_status(
            node_id=node_id,
            online=bool(data.get("online", False)),
            rssi=int(data.get("rssi", -127)),
            csi_active=bool(data.get("csi_active", False)),
        )
