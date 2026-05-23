"""
In-memory system state shared across all pipeline components.

All writes are protected by asyncio locks so concurrent MQTT handlers
and the inference loop can safely update state without race conditions.
"""

import asyncio
import time
from dataclasses import dataclass, field
from typing import Optional
import numpy as np


@dataclass
class NodeState:
    node_id: str
    online: bool = False
    last_seen: float = 0.0
    rssi: int = -127
    csi_active: bool = False
    frames_received: int = 0
    # Ring buffer: most recent `window_size` amplitude arrays
    amp_buffer: list = field(default_factory=list)
    phase_buffer: list = field(default_factory=list)
    motion_buffer: list = field(default_factory=list)


@dataclass
class PresenceState:
    present: bool = False
    confidence: float = 0.0
    person_count: int = 0
    zone: str = ""
    updated_at: float = 0.0


@dataclass
class Joint:
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    confidence: float = 0.0


# COCO 17-joint skeleton order
JOINT_NAMES = [
    "nose", "left_eye", "right_eye", "left_ear", "right_ear",
    "left_shoulder", "right_shoulder", "left_elbow", "right_elbow",
    "left_wrist", "right_wrist", "left_hip", "right_hip",
    "left_knee", "right_knee", "left_ankle", "right_ankle",
]


@dataclass
class PoseState:
    joints: list[Joint] = field(default_factory=lambda: [Joint() for _ in range(17)])
    confidence: float = 0.0
    updated_at: float = 0.0

    def to_dict(self) -> dict:
        return {
            "confidence": self.confidence,
            "updated_at": self.updated_at,
            "joints": {
                name: {"x": j.x, "y": j.y, "z": j.z, "confidence": j.confidence}
                for name, j in zip(JOINT_NAMES, self.joints)
            },
        }


@dataclass
class VitalsState:
    breathing_rate: float = 0.0   # breaths per minute
    heart_rate: float = 0.0       # beats per minute
    breathing_confidence: float = 0.0
    heart_confidence: float = 0.0
    updated_at: float = 0.0


class SystemState:
    """Thread-safe shared state for the entire hub."""

    def __init__(self, node_ids: list[str], window_size: int = 30) -> None:
        self._lock = asyncio.Lock()
        self.window_size = window_size
        self.nodes: dict[str, NodeState] = {nid: NodeState(node_id=nid) for nid in node_ids}
        self.presence = PresenceState()
        self.pose = PoseState()
        self.vitals = VitalsState()
        self.inference_count = 0
        self.inference_latency_ms = 0.0
        self.started_at = time.time()

    async def update_node_csi(self, node_id: str, amplitude: list[float],
                               phase: list[float], motion_variance: float,
                               rssi: int, channel: int) -> None:
        async with self._lock:
            node = self.nodes.get(node_id)
            if node is None:
                return
            node.online = True
            node.last_seen = time.time()
            node.rssi = rssi
            node.csi_active = True
            node.frames_received += 1

            node.amp_buffer.append(amplitude)
            node.phase_buffer.append(phase)
            node.motion_buffer.append(motion_variance)

            if len(node.amp_buffer) > self.window_size:
                node.amp_buffer.pop(0)
                node.phase_buffer.pop(0)
                node.motion_buffer.pop(0)

    async def update_node_status(self, node_id: str, online: bool,
                                  rssi: int, csi_active: bool) -> None:
        async with self._lock:
            node = self.nodes.get(node_id)
            if node is None:
                return
            node.online = online
            node.rssi = rssi
            node.csi_active = csi_active
            if online:
                node.last_seen = time.time()

    async def update_presence(self, present: bool, confidence: float,
                               person_count: int, zone: str) -> None:
        async with self._lock:
            self.presence = PresenceState(
                present=present, confidence=confidence,
                person_count=person_count, zone=zone,
                updated_at=time.time(),
            )

    async def update_pose(self, joints_array: np.ndarray, confidence: float) -> None:
        """joints_array: shape (17, 4) — x, y, z, conf per joint."""
        async with self._lock:
            joints = [
                Joint(x=float(joints_array[i, 0]),
                      y=float(joints_array[i, 1]),
                      z=float(joints_array[i, 2]),
                      confidence=float(joints_array[i, 3]))
                for i in range(17)
            ]
            self.pose = PoseState(joints=joints, confidence=confidence,
                                  updated_at=time.time())

    async def update_vitals(self, breathing_rate: float, heart_rate: float,
                             br_conf: float, hr_conf: float) -> None:
        async with self._lock:
            self.vitals = VitalsState(
                breathing_rate=breathing_rate,
                heart_rate=heart_rate,
                breathing_confidence=br_conf,
                heart_confidence=hr_conf,
                updated_at=time.time(),
            )

    async def get_fused_window(self) -> Optional[np.ndarray]:
        """Return fused CSI window [window_size, n_nodes × 56] or None if insufficient data."""
        async with self._lock:
            node_list = list(self.nodes.values())
            min_frames = min(len(n.amp_buffer) for n in node_list)
            if min_frames < self.window_size:
                return None

            # Stack: [window_size, n_nodes, 56]
            stacked = np.array([
                [n.amp_buffer[i] for n in node_list]
                for i in range(self.window_size)
            ], dtype=np.float32)

            # Flatten to [window_size, n_nodes*56]
            return stacked.reshape(self.window_size, -1)

    async def get_motion_window(self) -> Optional[np.ndarray]:
        """Return motion variance window [window_size, n_nodes]."""
        async with self._lock:
            node_list = list(self.nodes.values())
            min_frames = min(len(n.motion_buffer) for n in node_list)
            if min_frames < self.window_size:
                return None
            return np.array([
                [n.motion_buffer[i] for n in node_list]
                for i in range(self.window_size)
            ], dtype=np.float32)

    async def snapshot(self) -> dict:
        async with self._lock:
            return {
                "nodes": {
                    nid: {
                        "online": n.online,
                        "rssi": n.rssi,
                        "last_seen": n.last_seen,
                        "frames_received": n.frames_received,
                        "buffer_fill": len(n.amp_buffer),
                    }
                    for nid, n in self.nodes.items()
                },
                "presence": {
                    "present": self.presence.present,
                    "confidence": round(self.presence.confidence, 3),
                    "person_count": self.presence.person_count,
                    "zone": self.presence.zone,
                    "updated_at": self.presence.updated_at,
                },
                "pose": self.pose.to_dict(),
                "vitals": {
                    "breathing_rate": round(self.vitals.breathing_rate, 1),
                    "heart_rate": round(self.vitals.heart_rate, 1),
                    "breathing_confidence": round(self.vitals.breathing_confidence, 3),
                    "heart_confidence": round(self.vitals.heart_confidence, 3),
                    "updated_at": self.vitals.updated_at,
                },
                "inference_count": self.inference_count,
                "inference_latency_ms": round(self.inference_latency_ms, 2),
                "uptime_s": round(time.time() - self.started_at, 1),
            }
