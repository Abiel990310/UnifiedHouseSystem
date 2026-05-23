"""
Hub configuration loaded from config.yaml (with optional config.local.yaml override).
"""

import os
import yaml
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class NodeConfig:
    id: str
    location: str = ""
    weight: float = 1.0


@dataclass
class ApiConfig:
    host: str = "0.0.0.0"
    port: int = 8080
    secure: bool = False


@dataclass
class MqttConfig:
    host: str = "127.0.0.1"
    port: int = 1883
    client_id: str = "ruview_hub"
    keepalive: int = 60


@dataclass
class PipelineConfig:
    window_size: int = 30
    inference_rate_hz: int = 10
    presence_threshold: float = 0.55
    max_persons: int = 3


@dataclass
class RoomConfig:
    width: float = 5.0
    height: float = 3.0
    depth: float = 4.0


@dataclass
class VitalsConfig:
    breathing_fft_window: int = 300
    heart_fft_window: int = 600
    breathing_range_hz: list = field(default_factory=lambda: [0.1, 0.5])
    heart_range_hz: list = field(default_factory=lambda: [0.8, 3.0])


@dataclass
class StorageConfig:
    db_path: str = "/var/lib/ruview/ruview.db"
    history_days: int = 7


@dataclass
class LoggingConfig:
    level: str = "INFO"
    file: str = "/var/log/ruview/hub.log"


@dataclass
class HubConfig:
    api: ApiConfig = field(default_factory=ApiConfig)
    mqtt: MqttConfig = field(default_factory=MqttConfig)
    nodes: list[NodeConfig] = field(default_factory=list)
    pipeline: PipelineConfig = field(default_factory=PipelineConfig)
    room: RoomConfig = field(default_factory=RoomConfig)
    vitals: VitalsConfig = field(default_factory=VitalsConfig)
    storage: StorageConfig = field(default_factory=StorageConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)


def _merge(base: dict, override: dict) -> dict:
    result = base.copy()
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(result.get(k), dict):
            result[k] = _merge(result[k], v)
        else:
            result[k] = v
    return result


def load_config(config_dir: Optional[str] = None) -> HubConfig:
    if config_dir is None:
        config_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    base_path  = os.path.join(config_dir, "config.yaml")
    local_path = os.path.join(config_dir, "config.local.yaml")

    with open(base_path) as f:
        data = yaml.safe_load(f)

    if os.path.exists(local_path):
        with open(local_path) as f:
            local = yaml.safe_load(f) or {}
        data = _merge(data, local)

    cfg = HubConfig()
    cfg.api      = ApiConfig(**data.get("api", {}))
    cfg.mqtt     = MqttConfig(**data.get("mqtt", {}))
    cfg.nodes    = [NodeConfig(**n) for n in data.get("nodes", [])]
    cfg.pipeline = PipelineConfig(**data.get("pipeline", {}))
    cfg.room     = RoomConfig(**data.get("room", {}))
    cfg.vitals   = VitalsConfig(**data.get("vitals", {}))
    cfg.storage  = StorageConfig(**data.get("storage", {}))
    cfg.logging  = LoggingConfig(**data.get("logging", {}))
    return cfg
