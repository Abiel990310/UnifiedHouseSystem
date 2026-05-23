"""
RuVector — lightweight numpy inference model for WiFi CSI person tracking.

Architecture (~55K parameters):
  Input:    [T=30, F=168]  (time × fused subcarrier features from 3 nodes)
  Conv1D:   F → 32, kernel 5, temporal feature extraction
  Conv1D:   32 → 64, kernel 3
  Attention: simple dot-product self-attention over time axis
  Pool:     temporal mean pooling → [64]
  Project:  [64] → [128] environment fingerprint
  Heads:
    presence_head:  [128] → [1]  sigmoid
    pose_head:      [128] → [51]  (17 joints × 3: x,y,confidence)
    vitals_head:    [128] → [2]  (breathing_rate, heart_rate — normalized)

Weights are randomly initialized on first use and must be trained on
real CSI data from your specific room. See scripts/train_model.py.
"""

import os
import logging
import time
import numpy as np

logger = logging.getLogger(__name__)

T = 30       # time window frames
F = 168      # 3 nodes × 56 subcarriers
D1 = 32      # first conv output channels
D2 = 64      # second conv output channels
D3 = 128     # embedding dimension
N_JOINTS = 17


def _relu(x: np.ndarray) -> np.ndarray:
    return np.maximum(0.0, x)


def _sigmoid(x: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.clip(x, -20, 20)))


def _layer_norm(x: np.ndarray, eps: float = 1e-6) -> np.ndarray:
    mean = x.mean(axis=-1, keepdims=True)
    std  = x.std(axis=-1, keepdims=True) + eps
    return (x - mean) / std


def _conv1d(x: np.ndarray, W: np.ndarray, b: np.ndarray, stride: int = 1) -> np.ndarray:
    """
    1D convolution.
    x: [T, C_in]
    W: [k, C_in, C_out]
    b: [C_out]
    Returns: [T', C_out] where T' = T - k + 1 (valid padding)
    """
    k, C_in, C_out = W.shape
    T_out = (x.shape[0] - k) // stride + 1
    out = np.zeros((T_out, C_out), dtype=np.float32)
    for t in range(T_out):
        patch = x[t * stride: t * stride + k]          # [k, C_in]
        out[t] = patch.reshape(-1) @ W.reshape(-1, C_out) + b
    return out


def _self_attention(x: np.ndarray, Wq: np.ndarray, Wk: np.ndarray,
                    Wv: np.ndarray, Wo: np.ndarray) -> np.ndarray:
    """
    Single-head scaled dot-product attention.
    x:  [T, D]
    W*: [D, D_head]
    Returns: [T, D]
    """
    Q = x @ Wq  # [T, D_head]
    K = x @ Wk
    V = x @ Wv

    scale = np.sqrt(Q.shape[-1]).astype(np.float32)
    scores = (Q @ K.T) / scale              # [T, T]
    attn   = np.exp(scores - scores.max(axis=-1, keepdims=True))
    attn   = attn / (attn.sum(axis=-1, keepdims=True) + 1e-8)
    ctx    = attn @ V                       # [T, D_head]
    return ctx @ Wo                         # [T, D]


def _linear(x: np.ndarray, W: np.ndarray, b: np.ndarray) -> np.ndarray:
    return x @ W + b


class RuVectorModel:
    """
    Numpy-based RuVector inference model.

    On first instantiation the weights are randomly initialized. Call
    load_weights(path) to load trained weights from a .npz file.
    """

    # Parameter dimensions
    PARAM_SHAPES = {
        "conv1_W":  (5, F, D1),
        "conv1_b":  (D1,),
        "conv2_W":  (3, D1, D2),
        "conv2_b":  (D2,),
        "attn_Wq":  (D2, D2),
        "attn_Wk":  (D2, D2),
        "attn_Wv":  (D2, D2),
        "attn_Wo":  (D2, D2),
        "proj_W":   (D2, D3),
        "proj_b":   (D3,),
        "pres_W":   (D3, 1),
        "pres_b":   (1,),
        "pose_W":   (D3, N_JOINTS * 3),
        "pose_b":   (N_JOINTS * 3,),
        "vital_W":  (D3, 2),
        "vital_b":  (2,),
    }

    def __init__(self, weights_path: str | None = None) -> None:
        self._weights: dict[str, np.ndarray] = {}
        self._calibrated = False
        self._baseline: np.ndarray | None = None

        if weights_path and os.path.exists(weights_path):
            self.load_weights(weights_path)
            logger.info("RuVector: loaded weights from %s", weights_path)
        else:
            self._init_random_weights()
            logger.warning(
                "RuVector: using random weights — run scripts/train_model.py "
                "to train on your room's CSI data."
            )

    def _init_random_weights(self) -> None:
        rng = np.random.default_rng(42)
        for name, shape in self.PARAM_SHAPES.items():
            if name.endswith("_b"):
                self._weights[name] = np.zeros(shape, dtype=np.float32)
            else:
                # Xavier / Glorot initialization
                fan_in  = int(np.prod(shape[:-1]))
                fan_out = shape[-1]
                limit   = np.sqrt(6.0 / (fan_in + fan_out))
                self._weights[name] = rng.uniform(
                    -limit, limit, shape).astype(np.float32)

    def load_weights(self, path: str) -> None:
        data = np.load(path)
        for name in self.PARAM_SHAPES:
            if name in data:
                self._weights[name] = data[name].astype(np.float32)
        self._calibrated = bool(data.get("calibrated", False))
        if "baseline" in data:
            self._baseline = data["baseline"].astype(np.float32)

    def save_weights(self, path: str) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        payload = dict(self._weights)
        payload["calibrated"] = np.array(self._calibrated)
        if self._baseline is not None:
            payload["baseline"] = self._baseline
        np.savez(path, **payload)
        logger.info("RuVector: saved weights to %s", path)

    def set_baseline(self, baseline: np.ndarray) -> None:
        """Set the empty-room baseline for differential CSI (from calibration)."""
        self._baseline = baseline.astype(np.float32)
        self._calibrated = True
        logger.info("RuVector: calibration baseline set")

    def infer(self, x: np.ndarray) -> dict:
        """
        Run inference on a fused CSI window.

        Args:
            x: [T, 168] fused CSI amplitude array.

        Returns:
            dict with keys: presence, confidence, joints, breathing_rate, heart_rate
        """
        t0 = time.perf_counter()
        w = self._weights

        # Input layer norm
        x = _layer_norm(x)                                          # [T, 168]

        # Conv1D block 1
        c1 = _conv1d(x, w["conv1_W"], w["conv1_b"])                # [T-4, D1]
        c1 = _relu(_layer_norm(c1))

        # Conv1D block 2
        c2 = _conv1d(c1, w["conv2_W"], w["conv2_b"])               # [T-6, D2]
        c2 = _relu(_layer_norm(c2))

        # Self-attention
        a = _self_attention(c2, w["attn_Wq"], w["attn_Wk"],
                             w["attn_Wv"], w["attn_Wo"])            # [T-6, D2]
        a = _layer_norm(c2 + a)                                     # residual

        # Temporal mean pooling
        pooled = a.mean(axis=0)                                     # [D2]

        # Environment fingerprint
        emb = _relu(_linear(pooled, w["proj_W"], w["proj_b"]))      # [D3]

        # Presence head
        pres_logit = _linear(emb, w["pres_W"], w["pres_b"])[0]
        presence_conf = float(_sigmoid(np.array([pres_logit]))[0])
        present = presence_conf >= 0.55

        # Pose head
        pose_raw = _linear(emb, w["pose_W"], w["pose_b"])           # [51]
        pose_raw = pose_raw.reshape(N_JOINTS, 3)
        # columns: x (0..1 room width), y (0..1 room height), confidence
        joints = np.zeros((N_JOINTS, 4), dtype=np.float32)
        joints[:, 0] = _sigmoid(pose_raw[:, 0])  # x normalized
        joints[:, 1] = _sigmoid(pose_raw[:, 1])  # y normalized
        joints[:, 2] = 0.0                         # z (not yet estimated)
        joints[:, 3] = _sigmoid(pose_raw[:, 2])  # per-joint confidence

        # Vitals head
        vitals = _linear(emb, w["vital_W"], w["vital_b"])
        # sigmoid output → scale to physiological ranges
        br = float(_sigmoid(vitals[0:1])[0]) * 30.0   # 0–30 breaths/min
        hr = float(_sigmoid(vitals[1:2])[0]) * 160.0 + 40.0  # 40–200 bpm

        latency_ms = (time.perf_counter() - t0) * 1000

        return {
            "present":         present,
            "confidence":      round(presence_conf, 4),
            "joints":          joints,
            "breathing_rate":  round(br, 1),
            "heart_rate":      round(hr, 1),
            "latency_ms":      round(latency_ms, 3),
        }

    @property
    def parameter_count(self) -> int:
        return sum(v.size for v in self._weights.values())
