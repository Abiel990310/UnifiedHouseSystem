"""
IrController — publishes MQTT commands to IR nodes and tracks their state.

No IP addresses needed. Nodes self-register via MQTT, just like LED nodes.
"""

import json
import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

IR_NODE_ID = "ir_1"   # default; can be overridden


@dataclass
class AcState:
    power: str = "off"   # "on" | "off"
    mode:  str = "cool"  # cool | heat | fan | dry | auto
    temp:  int = 25      # 16–30 °C
    fan:   str = "auto"  # auto | low | med | high


@dataclass
class LightState:
    power: str = "off"


@dataclass
class IrState:
    ac:     AcState    = field(default_factory=AcState)
    light:  LightState = field(default_factory=LightState)
    online: bool       = False


class IrController:
    """Thin wrapper around MQTT publish for IR node commands."""

    def __init__(self, node_id: str = IR_NODE_ID) -> None:
        self._node_id = node_id
        self.state    = IrState()
        logger.info("IrController node_id=%s", node_id)

    @property
    def topic_set(self) -> str:
        return f"home/ir/{self._node_id}/set"

    def update_from_status(self, data: dict) -> None:
        """Called by MqttClient when a heartbeat arrives."""
        self.state.online      = bool(data.get("online", False))
        self.state.ac.power    = data.get("ac_power",  self.state.ac.power)
        self.state.ac.temp     = int(data.get("ac_temp", self.state.ac.temp))
        self.state.light.power = data.get("light",     self.state.light.power)

    async def set_ac(self, mqtt, **kwargs) -> IrState:
        payload = {"device": "ac"}
        for k, v in kwargs.items():
            if v is not None:
                payload[k] = v
                if k == "power":   self.state.ac.power = v
                elif k == "mode":  self.state.ac.mode  = v
                elif k == "temp":  self.state.ac.temp  = int(v)
                elif k == "fan":   self.state.ac.fan   = v
        await mqtt.publish(self.topic_set, json.dumps(payload))
        logger.info("IR AC → %s", payload)
        return self.state

    async def set_light(self, mqtt, power: str) -> IrState:
        self.state.light.power = power
        await mqtt.publish(self.topic_set, json.dumps({"device": "light", "power": power}))
        logger.info("IR light → %s", power)
        return self.state
