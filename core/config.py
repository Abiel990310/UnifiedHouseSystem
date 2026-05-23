"""
Core platform configuration, shared by all modules.
"""

import os
from dataclasses import dataclass, field


@dataclass
class CoreConfig:
    log_level: str = field(default_factory=lambda: os.getenv("LOG_LEVEL", "INFO"))
    data_dir: str = field(default_factory=lambda: os.getenv("DATA_DIR", "/var/lib/unifiedhouse"))
    api_host: str = field(default_factory=lambda: os.getenv("API_HOST", "0.0.0.0"))
    api_port: int = field(default_factory=lambda: int(os.getenv("API_PORT", "8080")))
    secret_key: str = field(default_factory=lambda: os.getenv("SECRET_KEY", "change-me-in-production"))

    # Future: auth, TLS, plugin paths, etc.
