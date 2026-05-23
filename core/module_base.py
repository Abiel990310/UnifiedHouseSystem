"""
Base class for all UnifiedHouseSystem modules.

A module is a self-contained capability (e.g. RuView, lighting control).
Each module has a lifecycle: configure -> start -> run -> stop.
"""

import asyncio
import logging
from abc import ABC, abstractmethod
from typing import Any

from .event_bus import EventBus, Event, bus as global_bus


class BaseModule(ABC):
    """
    Abstract base for house system modules.

    Subclasses implement start() / stop() and use self.publish() to emit events
    and self.subscribe() to react to events from other modules.
    """

    def __init__(self, module_id: str, event_bus: EventBus | None = None) -> None:
        self.module_id = module_id
        self.bus = event_bus or global_bus
        self.logger = logging.getLogger(f"module.{module_id}")
        self._running = False

    @property
    def running(self) -> bool:
        return self._running

    @abstractmethod
    async def start(self) -> None:
        """Initialize resources and begin processing."""

    @abstractmethod
    async def stop(self) -> None:
        """Release resources and shut down cleanly."""

    async def publish(self, topic: str, payload: Any) -> None:
        await self.bus.publish(Event(topic=topic, payload=payload, source=self.module_id))

    def subscribe(self, topic: str):
        return self.bus.subscribe(topic)

    async def health_check(self) -> dict[str, Any]:
        """Return a dict describing the module's current health."""
        return {"module_id": self.module_id, "running": self._running}

    def __repr__(self) -> str:
        state = "running" if self._running else "stopped"
        return f"<{self.__class__.__name__} id={self.module_id!r} {state}>"
