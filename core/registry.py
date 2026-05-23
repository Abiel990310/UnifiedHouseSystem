"""
Module registry — tracks all loaded house system modules and their lifecycle.
"""

import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .module_base import BaseModule

logger = logging.getLogger(__name__)


class ModuleRegistry:
    """Central registry for all active house system modules."""

    def __init__(self) -> None:
        self._modules: dict[str, "BaseModule"] = {}

    def register(self, module: "BaseModule") -> None:
        if module.module_id in self._modules:
            raise ValueError(f"Module {module.module_id!r} already registered")
        self._modules[module.module_id] = module
        logger.info("Registered module: %s", module.module_id)

    def unregister(self, module_id: str) -> None:
        self._modules.pop(module_id, None)

    def get(self, module_id: str) -> "BaseModule | None":
        return self._modules.get(module_id)

    def list_modules(self) -> list[dict]:
        return [
            {"module_id": m.module_id, "type": type(m).__name__, "running": m.running}
            for m in self._modules.values()
        ]

    async def start_all(self) -> None:
        for module in self._modules.values():
            logger.info("Starting module: %s", module.module_id)
            await module.start()

    async def stop_all(self) -> None:
        for module in reversed(list(self._modules.values())):
            logger.info("Stopping module: %s", module.module_id)
            await module.stop()

    async def health_check_all(self) -> dict[str, dict]:
        results = {}
        for module_id, module in self._modules.items():
            results[module_id] = await module.health_check()
        return results


registry = ModuleRegistry()
