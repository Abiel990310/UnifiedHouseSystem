"""
Multi-node CSI fusion.

Takes the per-node amplitude windows and produces a single fused feature
matrix [T, N_nodes × N_subcarriers] ready for RuVector inference.
Applies per-node gain normalization and outlier rejection.
"""

import numpy as np
import logging

logger = logging.getLogger(__name__)

N_SUBCARRIERS = 56


def fuse_nodes(
    window: np.ndarray,
    node_weights: list[float] | None = None,
    baseline: np.ndarray | None = None,
) -> np.ndarray:
    """
    Fuse multi-node CSI into a single feature matrix.

    Args:
        window:        [T, N_nodes * N_subcarriers] float32 amplitude array.
        node_weights:  Per-node fusion weights (length N_nodes). Default: equal.
        baseline:      Empty-room baseline [N_nodes * N_subcarriers], for
                       differential CSI. If None, uses per-window mean.

    Returns:
        fused: [T, N_nodes * N_subcarriers] normalized float32 array.
    """
    T, total_features = window.shape
    n_nodes = total_features // N_SUBCARRIERS

    if node_weights is None:
        node_weights = [1.0] * n_nodes
    weights = np.array(node_weights, dtype=np.float32)

    # Reshape to [T, N_nodes, N_subcarriers]
    w = window.reshape(T, n_nodes, N_SUBCARRIERS)

    # Differential: subtract baseline (or per-node temporal mean as proxy)
    if baseline is not None:
        b = baseline.reshape(n_nodes, N_SUBCARRIERS)
        w = w - b[np.newaxis, :, :]
    else:
        node_means = w.mean(axis=0, keepdims=True)  # [1, N_nodes, N_subcarriers]
        w = w - node_means

    # Per-node amplitude normalization (L2 over subcarriers)
    node_norms = np.linalg.norm(w, axis=2, keepdims=True) + 1e-8
    w = w / node_norms

    # Apply node fusion weights
    w = w * weights[np.newaxis, :, np.newaxis]

    # Hampel-style outlier clamp (3-sigma per node per subcarrier)
    std = w.std(axis=0, keepdims=True) + 1e-8
    mean = w.mean(axis=0, keepdims=True)
    w = np.clip(w, mean - 3 * std, mean + 3 * std)

    # Flatten back to [T, N_nodes * N_subcarriers]
    return w.reshape(T, total_features).astype(np.float32)


def compute_motion_energy(motion_window: np.ndarray) -> float:
    """
    Compute overall motion energy from the motion variance buffer.

    Args:
        motion_window: [T, N_nodes] motion variance values.
    Returns:
        Scalar energy score 0..1.
    """
    energy = float(motion_window.mean())
    return float(np.clip(energy / 500.0, 0.0, 1.0))
