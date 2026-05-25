"""
Async MQTT subscriber that feeds incoming CSI frames into SystemState.
Also subscribes to LED node status heartbeats and exposes a publish() method.
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

        # LED node state tracked from MQTT heartbeats
        self.led_nodes: dict = {}

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

    async def publish(self, topic: str, payload: str, retain: bool = False) -> None:
        """Publish a single message via a short-lived connection."""
        try:
            async with aiomqtt.Client(
                hostname=self._cfg.host,
                port=self._cfg.port,
                identifier=f"{self._cfg.client_id}_pub",
            ) as client:
                await client.publish(topic, payload, retain=retain)
        except Exception as exc:
            logger.warning("MQTT publish error on %s: %s", topic, exc)
            raise

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

                    await client.subscribe(Topics.NODE_CSI,       qos=0)
                    await client.subscribe(Topics.NODE_STATUS,     qos=1)
                    await client.subscribe(Topics.LED_STATUS_SUB,  qos=1)
                    logger.info("Subscribed to CSI, node status, and LED status topics")

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

        if topic.endswith("/csi"):
            node_id = Topics.node_id_from_topic(topic)
            await self._handle_csi(node_id, data)
        elif "/node/" in topic and topic.endswith("/status"):
            node_id = Topics.node_id_from_topic(topic)
            await self._handle_status(node_id, data)
        elif topic.startswith("home/led/") and topic.endswith("/status"):
            led_id = Topics.led_id_from_status_topic(topic)
            self._handle_led_status(led_id, data)

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

    def _handle_led_status(self, led_id: str, data: dict) -> None:
        if not led_id:
            return
        self.led_nodes[led_id] = {
            "online":     bool(data.get("online", False)),
            "preset":     data.get("preset", "off"),
            "brightness": int(data.get("brightness", 0)),
            "rssi":       int(data.get("rssi", -127)),
            "last_seen":  time.time(),
        }
        logger.debug("LED %s  preset=%s  rssi=%d", led_id,
                     self.led_nodes[led_id]["preset"], self.led_nodes[led_id]["rssi"])
