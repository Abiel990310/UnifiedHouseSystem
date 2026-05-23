#!/usr/bin/env python3
"""
RuView training data collector — run this on the Raspberry Pi.

Guides you through a simple recording session:
  Round 1-5: stand in room for 30s  (labeled "present")
  Round 1-5: leave room for 30s     (labeled "absent")

Saves data to ~/ruview_training_data/ as JSONL files.
Run train_on_pc.py on your computer afterwards to train the model.

Usage:
  python3 collect_training_data.py
"""

import sys, os, json, time, asyncio
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../hub/src"))

import aiomqtt

DATA_DIR   = os.path.expanduser("~/ruview_training_data")
MQTT_HOST  = "localhost"
MQTT_PORT  = 1883
TOPIC_CSI  = "ruview/node/+/csi"
ROUND_SECS = 30   # seconds per round
N_ROUNDS   = 5    # rounds of present + absent each


os.makedirs(DATA_DIR, exist_ok=True)

# ── Shared CSI buffer ─────────────────────────────────────────────────────────
csi_buffer: dict[str, dict] = {}   # node_id → latest CSI frame


async def mqtt_listener():
    """Background task: keep csi_buffer updated with latest frames."""
    async with aiomqtt.Client(MQTT_HOST, MQTT_PORT) as client:
        await client.subscribe(TOPIC_CSI)
        async for msg in client.messages:
            try:
                data    = json.loads(msg.payload)
                node_id = str(msg.topic).split("/")[2]
                csi_buffer[node_id] = data
            except Exception:
                pass


async def record_round(label: str, round_num: int):
    """Record ROUND_SECS of CSI frames with a given label."""
    filename = os.path.join(DATA_DIR, f"{label}_round{round_num}_{int(time.time())}.jsonl")
    frames   = 0

    print(f"\n  Recording {ROUND_SECS}s of '{label}' data...", flush=True)
    t_end = time.time() + ROUND_SECS

    with open(filename, "w") as f:
        while time.time() < t_end:
            remaining = int(t_end - time.time())
            if csi_buffer:
                # Build a fused feature vector from all available nodes
                node_data = {}
                for nid, frame in csi_buffer.items():
                    node_data[nid] = frame.get("a", [])  # amplitude array

                record = {
                    "ts":               time.time(),
                    "label_presence":   1 if label == "present" else 0,
                    "label_breathing":  0.0,
                    "label_heart":      0.0,
                    "node_data":        node_data,
                    "motion_variance":  {
                        nid: csi_buffer[nid].get("mv", 0) for nid in csi_buffer
                    },
                }
                f.write(json.dumps(record) + "\n")
                frames += 1

            # Progress bar
            done = ROUND_SECS - remaining
            bar  = "█" * done + "░" * remaining
            print(f"  [{bar}] {remaining:2d}s left  ({frames} frames)  ", end="\r", flush=True)
            await asyncio.sleep(0.1)

    print(f"\n  Saved {frames} frames → {filename}")
    return frames


async def main():
    print("\n" + "="*55)
    print("  RuView Training Data Collector")
    print("="*55)
    print(f"\n  Data will be saved to: {DATA_DIR}")
    print(f"  Each round: {ROUND_SECS} seconds")
    print(f"  Total rounds: {N_ROUNDS} present + {N_ROUNDS} absent")
    print(f"  Total time: ~{N_ROUNDS * 2 * ROUND_SECS // 60} minutes\n")

    # Start MQTT listener in background
    listener = asyncio.create_task(mqtt_listener())

    # Wait for nodes to connect
    print("  Waiting for ESP32 nodes to connect...", end="", flush=True)
    for _ in range(30):
        if csi_buffer:
            break
        await asyncio.sleep(1)
        print(".", end="", flush=True)

    if not csi_buffer:
        print("\n\n  ERROR: No CSI data received.")
        print("  Make sure the ESP32 nodes are powered on and connected.")
        return

    print(f"\n  Nodes connected: {list(csi_buffer.keys())}\n")

    total_frames = 0

    for round_num in range(1, N_ROUNDS + 1):
        print(f"\n{'─'*55}")
        print(f"  ROUND {round_num}/{N_ROUNDS}")

        # ── PRESENT ──────────────────────────────────────────────────────
        print(f"\n  Step 1: WALK INTO THE ROOM and stand normally.")
        print("  Press Enter when you are in the room...")
        input()
        await asyncio.sleep(2)  # settle time
        total_frames += await record_round("present", round_num)

        # ── ABSENT ───────────────────────────────────────────────────────
        print(f"\n  Step 2: LEAVE THE ROOM completely.")
        print("  Press Enter when the room is empty...")
        input()
        await asyncio.sleep(2)
        total_frames += await record_round("absent", round_num)

    listener.cancel()

    print(f"\n{'='*55}")
    print(f"  Collection complete!")
    print(f"  Total frames recorded: {total_frames}")
    print(f"  Data saved in: {DATA_DIR}")
    print()
    print("  NEXT STEP:")
    print("  Copy the training data to your computer and run:")
    print("  python train_on_pc.py")
    print(f"{'='*55}\n")


if __name__ == "__main__":
    asyncio.run(main())
