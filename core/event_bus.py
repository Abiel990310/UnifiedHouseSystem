"""
Central event bus for inter-module communication.

All house system modules publish and subscribe to events through this bus.
Supports async handlers, wildcards, and priority ordering.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Awaitable
from datetime import datetime, timezone
import uuid

logger = logging.getLogger(__name__)


@dataclass
class Event:
    topic: str
    payload: Any
    source: str = ""
    event_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __repr__(self) -> str:
        return f"Event(topic={self.topic!r}, source={self.source!r}, id={self.event_id})"


Handler = Callable[[Event], Awaitable[None]]


class EventBus:
    """
    Async publish/subscribe event bus.

    Topic patterns support single-level wildcards with '+' and
    multi-level wildcards with '#' (MQTT-style).

    Example::

        bus = EventBus()

        @bus.subscribe("ruview/presence")
        async def on_presence(event: Event):
            print(event.payload)

        await bus.publish(Event("ruview/presence", {"present": True}, source="ruview"))
    """

    def __init__(self) -> None:
        self._handlers: dict[str, list[Handler]] = {}
        self._loop: asyncio.AbstractEventLoop | None = None

    def _get_loop(self) -> asyncio.AbstractEventLoop:
        if self._loop is None:
            self._loop = asyncio.get_event_loop()
        return self._loop

    def subscribe(self, topic: str):
        """Decorator to register an async handler for a topic pattern."""
        def decorator(fn: Handler) -> Handler:
            self._handlers.setdefault(topic, []).append(fn)
            logger.debug("Subscribed %s to topic %r", fn.__name__, topic)
            return fn
        return decorator

    def unsubscribe(self, topic: str, fn: Handler) -> None:
        if topic in self._handlers:
            self._handlers[topic] = [h for h in self._handlers[topic] if h is not fn]

    async def publish(self, event: Event) -> None:
        """Publish an event to all matching subscribers."""
        matched: list[Handler] = []
        for pattern, handlers in self._handlers.items():
            if self._topic_matches(pattern, event.topic):
                matched.extend(handlers)

        if not matched:
            return

        tasks = [asyncio.create_task(h(event)) for h in matched]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for result in results:
            if isinstance(result, Exception):
                logger.error("Event handler raised: %s", result)

    def publish_sync(self, event: Event) -> None:
        """Fire-and-forget from synchronous context."""
        loop = self._get_loop()
        if loop.is_running():
            asyncio.ensure_future(self.publish(event))
        else:
            loop.run_until_complete(self.publish(event))

    @staticmethod
    def _topic_matches(pattern: str, topic: str) -> bool:
        if pattern == topic:
            return True
        p_parts = pattern.split("/")
        t_parts = topic.split("/")
        for i, p in enumerate(p_parts):
            if p == "#":
                return True
            if i >= len(t_parts):
                return False
            if p != "+" and p != t_parts[i]:
                return False
        return len(p_parts) == len(t_parts)


# Global singleton — modules import this directly
bus = EventBus()
