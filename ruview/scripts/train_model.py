#!/usr/bin/env python3
"""
RuVector model training script.

Trains the RuVector model on labeled CSI data collected from your specific
room. Labeled data is expected as a CSV or directory of JSON frames captured
while performing known activities (present / absent / specific poses).

Usage:
  python train_model.py --data-dir ./data/labeled --epochs 200 --output ./weights/ruvector.npz

Data format (JSON per frame, one per line):
  {
    "features": [[...56 floats node_1 amp...], [...node_2...], [...node_3...]],
    "label_presence": 1,          // 1=present, 0=absent
    "label_pose": [[x,y,c], ...], // optional: 17×3 joints (normalized 0..1)
    "label_breathing": 15.2,      // optional: breaths/min
    "label_heart": 72.0           // optional: bpm
  }

Collection tip: run `python calibrate.py --record` to capture labeled frames.
"""

import argparse
import json
import os
import sys
import logging
import time
import numpy as np

# Allow running from repo root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "hub", "src"))

from pipeline.ruvector import RuVectorModel, _relu, _sigmoid, _layer_norm, T, F, D1, D2, D3

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)-8s] %(message)s")
logger = logging.getLogger("train")

N_JOINTS = 17


def load_dataset(data_dir: str, window_size: int = 30):
    """Load labeled frames and build sliding-window training samples."""
    frames = []
    for fname in sorted(os.listdir(data_dir)):
        if not fname.endswith(".jsonl") and not fname.endswith(".json"):
            continue
        with open(os.path.join(data_dir, fname)) as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        frames.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass

    logger.info("Loaded %d labeled frames from %s", len(frames), data_dir)
    if len(frames) < window_size + 10:
        raise ValueError(f"Need at least {window_size + 10} frames, got {len(frames)}")

    X, y_pres, y_pose, y_vitals = [], [], [], []
    for i in range(len(frames) - window_size):
        window_frames = frames[i: i + window_size]
        # Stack: [window_size, n_nodes * 56]
        feat = np.array([
            [v for node_amp in f["features"] for v in node_amp]
            for f in window_frames
        ], dtype=np.float32)

        label = frames[i + window_size]
        X.append(feat)
        y_pres.append(float(label.get("label_presence", 0)))

        pose = label.get("label_pose")
        if pose:
            y_pose.append(np.array(pose, dtype=np.float32).reshape(N_JOINTS * 3))
        else:
            y_pose.append(np.zeros(N_JOINTS * 3, dtype=np.float32))

        br = label.get("label_breathing", 0.0)
        hr = label.get("label_heart", 0.0)
        # Normalize vitals to sigmoid output range
        y_vitals.append([
            np.clip(br / 30.0, 0, 1),
            np.clip((hr - 40.0) / 160.0, 0, 1),
        ])

    return (np.array(X, dtype=np.float32),
            np.array(y_pres, dtype=np.float32),
            np.array(y_pose, dtype=np.float32),
            np.array(y_vitals, dtype=np.float32))


def forward(w, x):
    """Forward pass — mirrors RuVectorModel.infer() for gradient computation."""
    from pipeline.ruvector import _conv1d, _self_attention, _linear
    x = _layer_norm(x)
    c1 = _relu(_layer_norm(_conv1d(x, w["conv1_W"], w["conv1_b"])))
    c2 = _relu(_layer_norm(_conv1d(c1, w["conv2_W"], w["conv2_b"])))
    a  = _self_attention(c2, w["attn_Wq"], w["attn_Wk"], w["attn_Wv"], w["attn_Wo"])
    a  = _layer_norm(c2 + a)
    pooled = a.mean(axis=0)
    emb    = _relu(_linear(pooled, w["proj_W"], w["proj_b"]))
    pres   = _sigmoid(np.array([_linear(emb, w["pres_W"], w["pres_b"])[0]]))[0]
    pose   = _sigmoid(_linear(emb, w["pose_W"], w["pose_b"]))
    vitals = _sigmoid(_linear(emb, w["vital_W"], w["vital_b"]))
    return pres, pose, vitals, emb


def bce_loss(pred, target, eps=1e-7):
    pred = np.clip(pred, eps, 1 - eps)
    return -float(target * np.log(pred) + (1 - target) * np.log(1 - pred))


def mse_loss(pred, target):
    return float(np.mean((pred - target) ** 2))


def train(args):
    logger.info("Loading dataset from: %s", args.data_dir)
    X, y_pres, y_pose, y_vitals = load_dataset(args.data_dir)
    N = len(X)
    logger.info("Training samples: %d", N)

    model = RuVectorModel(weights_path=args.weights_in if args.weights_in and os.path.exists(args.weights_in) else None)
    w = model._weights

    lr         = args.lr
    batch_size = min(args.batch_size, N)
    rng        = np.random.default_rng(0)

    for epoch in range(1, args.epochs + 1):
        indices = rng.permutation(N)
        epoch_loss = 0.0
        n_batches  = 0

        for start in range(0, N - batch_size, batch_size):
            batch_idx = indices[start: start + batch_size]
            grad_acc  = {k: np.zeros_like(v) for k, v in w.items()}
            batch_loss = 0.0

            for idx in batch_idx:
                pres_pred, pose_pred, vitals_pred, emb = forward(w, X[idx])

                # Presence loss + gradient (manual BCE gradient)
                pres_target = y_pres[idx]
                loss_p = bce_loss(pres_pred, pres_target)
                dpres  = pres_pred - pres_target  # BCE gradient w.r.t. logit

                # Pose MSE loss
                loss_pose = mse_loss(pose_pred, y_pose[idx])
                dpose     = (pose_pred - y_pose[idx]) * 2 / len(pose_pred)

                # Vitals MSE loss
                loss_vitals = mse_loss(vitals_pred, y_vitals[idx])
                dvitals     = (vitals_pred - y_vitals[idx]) * 2 / len(vitals_pred)

                batch_loss += loss_p + 0.1 * loss_pose + 0.05 * loss_vitals

                # Backprop through output heads into emb
                # Gradient w.r.t. pres_W, pres_b
                grad_acc["pres_W"] += np.outer(emb, [dpres])
                grad_acc["pres_b"] += np.array([dpres])
                grad_acc["pose_W"] += np.outer(emb, dpose)
                grad_acc["pose_b"] += dpose
                grad_acc["vital_W"] += np.outer(emb, dvitals)
                grad_acc["vital_b"] += dvitals

            # SGD update (heads only — simpler than full backprop)
            for k in ["pres_W", "pres_b", "pose_W", "pose_b", "vital_W", "vital_b"]:
                w[k] -= (lr / batch_size) * grad_acc[k]

            epoch_loss += batch_loss / batch_size
            n_batches  += 1

        if epoch % 10 == 0 or epoch == 1:
            avg_loss = epoch_loss / max(n_batches, 1)
            logger.info("Epoch %4d/%d — loss: %.4f", epoch, args.epochs, avg_loss)

    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
    model.save_weights(args.output)
    logger.info("Training complete. Weights saved to %s", args.output)
    logger.info("Model has %d parameters.", model.parameter_count)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Train RuVector model on labeled CSI data")
    parser.add_argument("--data-dir",   required=True, help="Directory with labeled .jsonl files")
    parser.add_argument("--output",     default="weights/ruvector.npz", help="Output weights file")
    parser.add_argument("--weights-in", default=None, help="Pre-trained weights to continue from")
    parser.add_argument("--epochs",     type=int,   default=200)
    parser.add_argument("--lr",         type=float, default=1e-3)
    parser.add_argument("--batch-size", type=int,   default=32)
    args = parser.parse_args()
    train(args)
