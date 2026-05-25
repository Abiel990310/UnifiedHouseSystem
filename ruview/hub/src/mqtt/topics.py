"""
MQTT topic constants — must match firmware config.h exactly.
"""


class Topics:
    # Subscriptions (hub listens) — CSI nodes
    NODE_CSI    = "ruview/node/+/csi"
    NODE_STATUS = "ruview/node/+/status"

    # Publications (hub publishes processed results)
    PRESENCE = "ruview/system/presence"
    POSE     = "ruview/system/pose"
    VITALS   = "ruview/system/vitals"

    # LED nodes
    LED_ALL        = "home/led/all/set"
    LED_STATUS_SUB = "home/led/+/status"

    # IR nodes
    IR_STATUS_SUB = "home/ir/+/status"

    @staticmethod
    def led_set(node_id: str) -> str:
        return f"home/led/{node_id}/set"

    @staticmethod
    def node_id_from_topic(topic: str) -> str:
        """Extract node ID from e.g. 'ruview/node/node_1/csi' → 'node_1'."""
        parts = topic.split("/")
        return parts[2] if len(parts) >= 3 else ""

    @staticmethod
    def device_id_from_home_topic(topic: str) -> str:
        """Extract node ID from e.g. 'home/led/led_1/status' or 'home/ir/ir_1/status' → third segment."""
        parts = topic.split("/")
        return parts[2] if len(parts) >= 4 else ""
