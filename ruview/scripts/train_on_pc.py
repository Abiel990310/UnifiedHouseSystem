#!/usr/bin/env python3
"""
RuVector trainer — run this on your PC (not the Pi) after collecting data.

Requirements (install once):
  pip install numpy

Usage:
  1. Copy ~/ruview_training_data/ from Pi to your PC
  2. Run: python train_on_pc.py --data-dir ruview_training_data
  3. Copy the output ruvector_weights.npz back to the Pi:
     scp ruvector_weights.npz admin@192.168.1.189:/var/lib/ruview/

Then restart the hub:
  sudo systemctl restart ruview
"""

import argparse, os, sys, json, time, glob
import numpy as np

N_SUBCARRIERS = 56
WINDOW_SIZE   = 30   # frames per training sample
EPOCHS        = 500
LR            = 5e-4
BATCH         = 16


# ── Model parameter shapes (must match ruvector.py) ──────────────────────────
SHAPES = {
    "conv1_W": (5, 168, 32), "conv1_b": (32,),
    "conv2_W": (3, 32,  64), "conv2_b": (64,),
    "attn_Wq": (64, 64), "attn_Wk": (64, 64),
    "attn_Wv": (64, 64), "attn_Wo": (64, 64),
    "proj_W":  (64, 128), "proj_b": (128,),
    "pres_W":  (128, 1),  "pres_b": (1,),
    "pose_W":  (128, 51), "pose_b": (51,),
    "vital_W": (128, 2),  "vital_b": (2,),
}


def xavier(shape, rng):
    fan = int(np.prod(shape[:-1])) + shape[-1]
    lim = np.sqrt(6.0 / fan)
    return rng.uniform(-lim, lim, shape).astype(np.float32)


def init_weights(rng):
    w = {}
    for name, shape in SHAPES.items():
        w[name] = np.zeros(shape, np.float32) if name.endswith("_b") else xavier(shape, rng)
    return w


def relu(x):   return np.maximum(0, x)
def sigmoid(x): return 1.0 / (1.0 + np.exp(-np.clip(x, -20, 20)))
def lnorm(x, eps=1e-6):
    return (x - x.mean(-1, keepdims=True)) / (x.std(-1, keepdims=True) + eps)


def conv1d(x, W, b):
    k, Ci, Co = W.shape
    T = x.shape[0] - k + 1
    out = np.zeros((T, Co), np.float32)
    for t in range(T):
        out[t] = x[t:t+k].reshape(-1) @ W.reshape(-1, Co) + b
    return out


def attention(x, Wq, Wk, Wv, Wo):
    Q, K, V = x@Wq, x@Wk, x@Wv
    s = Q.shape[-1] ** 0.5
    A = np.exp((Q@K.T)/s - (Q@K.T).max(-1, keepdims=True))
    A /= A.sum(-1, keepdims=True) + 1e-8
    return (A@V) @ Wo


def forward(w, x):
    x  = lnorm(x)
    c1 = relu(lnorm(conv1d(x,  w["conv1_W"], w["conv1_b"])))
    c2 = relu(lnorm(conv1d(c1, w["conv2_W"], w["conv2_b"])))
    a  = lnorm(c2 + attention(c2, w["attn_Wq"], w["attn_Wk"], w["attn_Wv"], w["attn_Wo"]))
    p  = relu(a.mean(0) @ w["proj_W"] + w["proj_b"])
    pr = sigmoid((p @ w["pres_W"] + w["pres_b"])[0])
    return pr, p


# ── Dataset loading ───────────────────────────────────────────────────────────

def load_data(data_dir):
    files  = glob.glob(os.path.join(data_dir, "*.jsonl"))
    if not files:
        print(f"ERROR: No .jsonl files found in {data_dir}")
        sys.exit(1)

    frames = []
    for f in sorted(files):
        with open(f) as fh:
            for line in fh:
                line = line.strip()
                if line:
                    try:
                        frames.append(json.loads(line))
                    except Exception:
                        pass

    print(f"Loaded {len(frames)} frames from {len(files)} files")

    # Get all node IDs
    node_ids = sorted({nid for fr in frames for nid in fr.get("node_data", {})})
    if not node_ids:
        print("ERROR: No node CSI data found in frames")
        sys.exit(1)
    print(f"Nodes: {node_ids}")

    # Build windowed samples
    X, Y = [], []
    for i in range(len(frames) - WINDOW_SIZE):
        window = frames[i: i + WINDOW_SIZE]

        # Stack node amplitudes → [WINDOW_SIZE, n_nodes * 56]
        feat_rows = []
        for fr in window:
            row = []
            for nid in node_ids:
                amp = fr["node_data"].get(nid, [0.0] * N_SUBCARRIERS)
                amp = amp[:N_SUBCARRIERS] + [0.0] * max(0, N_SUBCARRIERS - len(amp))
                row.extend(amp)
            feat_rows.append(row)

        x = np.array(feat_rows, dtype=np.float32)

        # Pad or trim to 168 features (3 nodes × 56)
        if x.shape[1] < 168:
            x = np.pad(x, ((0,0),(0, 168 - x.shape[1])))
        else:
            x = x[:, :168]

        label = float(frames[i + WINDOW_SIZE].get("label_presence", 0))
        X.append(x)
        Y.append(label)

    X = np.array(X, dtype=np.float32)
    Y = np.array(Y, dtype=np.float32)

    n_present = int(Y.sum())
    print(f"Samples: {len(X)} total — {n_present} present, {len(X)-n_present} absent")
    return X, Y


# ── Training loop ─────────────────────────────────────────────────────────────

def train(data_dir, output_path):
    X, Y = load_data(data_dir)
    rng  = np.random.default_rng(42)
    w    = init_weights(rng)

    best_acc  = 0.0
    best_w    = {k: v.copy() for k, v in w.items()}

    print(f"\nTraining for {EPOCHS} epochs (batch={BATCH}, lr={LR})...")
    print("─" * 50)

    for epoch in range(1, EPOCHS + 1):
        idx = rng.permutation(len(X))
        epoch_loss = 0.0
        n_batches  = 0

        for start in range(0, len(X) - BATCH, BATCH):
            batch = idx[start: start + BATCH]
            g_pw  = np.zeros_like(w["pres_W"])
            g_pb  = np.zeros_like(w["pres_b"])

            batch_loss = 0.0
            for bi in batch:
                pr, emb = forward(w, X[bi])
                target   = Y[bi]
                eps      = 1e-7
                pr_c     = np.clip(pr, eps, 1-eps)
                loss     = -(target * np.log(pr_c) + (1-target) * np.log(1-pr_c))
                d        = pr - target   # BCE gradient

                g_pw += np.outer(emb, [d])
                g_pb += [d]
                batch_loss += loss

            # SGD update
            w["pres_W"] -= LR / BATCH * g_pw
            w["pres_b"] -= LR / BATCH * g_pb

            epoch_loss += batch_loss / BATCH
            n_batches  += 1

        if epoch % 50 == 0 or epoch == 1:
            # Evaluate accuracy
            correct = 0
            for i in range(len(X)):
                pr, _ = forward(w, X[i])
                pred  = 1 if pr >= 0.5 else 0
                if pred == int(Y[i]):
                    correct += 1
            acc = correct / len(X) * 100

            avg_loss = epoch_loss / max(n_batches, 1)
            print(f"Epoch {epoch:4d}/{EPOCHS}  loss={avg_loss:.4f}  accuracy={acc:.1f}%")

            if acc > best_acc:
                best_acc = acc
                best_w   = {k: v.copy() for k, v in w.items()}

    print(f"\nBest accuracy: {best_acc:.1f}%")

    # Save best weights
    payload = dict(best_w)
    payload["calibrated"] = np.array(True)
    np.savez(output_path, **payload)
    print(f"Weights saved to: {output_path}")
    print()
    print("NEXT STEP — copy weights to your Pi:")
    print(f"  scp {output_path} admin@192.168.1.189:/var/lib/ruview/ruvector_weights.npz")
    print()
    print("Then restart the hub:")
    print("  ssh admin@192.168.1.189 'sudo systemctl restart ruview'")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default="ruview_training_data",
                    help="Folder with .jsonl files from collect_training_data.py")
    ap.add_argument("--output",   default="ruvector_weights.npz",
                    help="Output weights file")
    args = ap.parse_args()
    train(args.data_dir, args.output)
