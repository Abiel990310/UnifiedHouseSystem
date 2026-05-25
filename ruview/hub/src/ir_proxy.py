"""
IrProxy — sends HTTP commands to the IR ESP32 node.

The IR ESP32 runs a lightweight HTTP server.  This class wraps it so
the rest of the hub code never has to know the ESP32's IP directly.
"""

import asyncio
import json
import logging
import urllib.request
import urllib.error
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

_TIMEOUT = 4.0   # seconds — generous for a local LAN call


@dataclass
class AcState:
    power: str = "off"   # "on" | "off"
    mode:  str = "cool"  # cool | heat | fan | dry | auto
    temp:  int = 25      # 16–30 °C
    fan:   str = "auto"  # auto | low | med | high


@dataclass
class LightState:
    power: str = "off"   # "on" | "off"


@dataclass
class IrState:
    ac:    AcState    = field(default_factory=AcState)
    light: LightState = field(default_factory=LightState)


class IrProxy:
    def __init__(self, esp32_ip: str, port: int = 80) -> None:
        self._base   = f"http://{esp32_ip}:{port}"
        self.state   = IrState()
        self.online  = False
        logger.info("IrProxy → %s", self._base)

    # ── Internal ──────────────────────────────────────────────────────────────

    def _post(self, path: str, body: dict) -> dict:
        """Blocking HTTP POST — always call via asyncio.to_thread."""
        url  = self._base + path
        data = json.dumps(body).encode()
        req  = urllib.request.Request(
            url, data=data, headers={"Content-Type": "application/json"}, method="POST"
        )
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            return json.loads(resp.read().decode())

    def _get(self, path: str) -> dict:
        url = self._base + path
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            return json.loads(resp.read().decode())

    def _apply_response(self, data: dict) -> None:
        """Update local state from the ESP32's JSON response."""
        ac = data.get("ac", {})
        if ac:
            self.state.ac.power = ac.get("power", self.state.ac.power)
            self.state.ac.mode  = ac.get("mode",  self.state.ac.mode)
            self.state.ac.temp  = int(ac.get("temp", self.state.ac.temp))
            self.state.ac.fan   = ac.get("fan",   self.state.ac.fan)
        lt = data.get("light", {})
        if lt:
            self.state.light.power = lt.get("power", self.state.light.power)
        self.online = data.get("online", True)

    # ── Public async API ──────────────────────────────────────────────────────

    async def set_ac(self, **kwargs) -> IrState:
        """
        kwargs: power, mode, temp, fan (all optional, only sent values change).
        """
        body = {k: v for k, v in kwargs.items() if v is not None}
        try:
            resp = await asyncio.to_thread(self._post, "/ac", body)
            self._apply_response(resp)
        except Exception as exc:
            self.online = False
            logger.warning("IrProxy set_ac failed: %s", exc)
            raise RuntimeError(f"IR node unreachable: {exc}") from exc
        return self.state

    async def set_light(self, power: str) -> IrState:
        try:
            resp = await asyncio.to_thread(self._post, "/light", {"power": power})
            self._apply_response(resp)
        except Exception as exc:
            self.online = False
            logger.warning("IrProxy set_light failed: %s", exc)
            raise RuntimeError(f"IR node unreachable: {exc}") from exc
        return self.state

    async def get_status(self) -> dict:
        try:
            data = await asyncio.to_thread(self._get, "/status")
            self._apply_response(data)
            return data
        except Exception as exc:
            self.online = False
            logger.debug("IrProxy status poll failed: %s", exc)
            return {"online": False}
