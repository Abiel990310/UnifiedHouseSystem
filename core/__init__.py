"""
UnifiedHouseSystem core platform.

Provides the event bus, module registry, and base module class that all
house system modules (RuView, lighting, climate, etc.) plug into.
"""

from .event_bus import EventBus, Event
from .module_base import BaseModule
from .registry import ModuleRegistry
from .config import CoreConfig

__all__ = ["EventBus", "Event", "BaseModule", "ModuleRegistry", "CoreConfig"]
