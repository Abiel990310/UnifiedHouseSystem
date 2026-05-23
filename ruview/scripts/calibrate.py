#!/usr/bin/env python3
"""
Room calibration tool.

Captures labeled CSI frames for training data collection, or directly
hits the /api/v1/calibrate endpoint to set the empty-room baseline.

Modes:
  --empty      Trigger empty-room baseline via API (30 second capture)
  --record     Record labeled frames to a JSONL file for training
  --test       Run inference on live data and print results

Usage:
  python calibrate.py --empty  --host 192.168.1.100
  python calibrate.py --record --host 192.168.1.100 --label absent --duration 60
  python calibrate.py --test   --host 192.168.1.100
"""

import argparse
import json
import sys
import time
import os
import urllib.request
import urllib.error


def api_get(host: str, port: int, path: str) -> dict:
    url = f"http://{host}:{port}{path}"
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            return json.loads(r.read())
    except urllib.error.URLError as e:
        print(f"  ERROR: {e}")
        return {}


def api_post(host: str, port: int, path: str) -> dict:
    url = f"http://{host}:{port}{path}"
    try:
        req = urllib.request.Request(url, data=b"", method="POST")
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read())
    except urllib.error.URLError as e:
        print(f"  ERROR: {e}")
        return {}


def cmd_empty(args):
    print(f"Triggering empty-room calibration on {args.host}:{args.port}...")
    print(">>> MAKE SURE THE ROOM IS COMPLETELY EMPTY <<<")
    print("Waiting 5 seconds before starting...")
    for i in range(5, 0, -1):
        print(f"  {i}...", end="\r", flush=True)
        time.sleep(1)
    print()

    result = api_post(args.host, args.port, "/api/v1/calibrate")
    if result:
        print(f"Calibration started: {result.get('message', 'OK')}")
        print(f"Duration: {result.get('duration_s', 10)}s — keep the room empty!")
    else:
        print("Failed to trigger calibration. Is the hub running?")


def cmd_test(args):
    print(f"Live inference from {args.host}:{args.port} — Ctrl+C to stop\n")
    try:
        while True:
            presence = api_get(args.host, args.port, "/api/v1/presence")
            vitals   = api_get(args.host, args.port, "/api/v1/vitals")
            nodes    = api_get(args.host, args.port, "/api/v1/nodes")

            node_status = " | ".join(
                f"{n.get('node_id','?')} {'OK' if n.get('online') else 'OFFLINE'} "
                f"({n.get('rssi',0)}dBm, buf={n.get('buffer_fill',0)}/30)"
                for n in nodes
            ) if nodes else "no nodes"

            present = presence.get("present", False)
            conf    = presence.get("confidence", 0)
            zone    = presence.get("zone", "")
            br      = vitals.get("breathing_rate", 0)
            hr      = vitals.get("heart_rate", 0)

            status = f"{'PRESENT' if present else 'absent':8s} ({conf*100:5.1f}%) zone={zone or '--':15s} | "
            status += f"BR={br:5.1f}bpm HR={hr:5.0f}bpm | {node_status}"
            print(f"\r{status}", end="", flush=True)
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\nDone.")


def cmd_record(args):
    import websocket  # pip install websocket-client
    output_file = args.output or f"data/labeled_{args.label}_{int(time.time())}.jsonl"
    os.makedirs(os.path.dirname(os.path.abspath(output_file)), exist_ok=True)

    print(f"Recording '{args.label}' frames for {args.duration}s → {output_file}")
    print("Connecting to WebSocket...")

    frames_recorded = 0
    t_end = time.time() + args.duration

    def on_message(ws, message):
        nonlocal frames_recorded
        if time.time() > t_end:
            ws.close()
            return
        try:
            data = json.loads(message)
            nodes_data = data.get("nodes", {})
            features = []
            for nid in sorted(nodes_data.keys()):
                # We only have buffer_fill from snapshot — for training we need
                # to subscribe to raw CSI topic via MQTT instead
                pass
            # For now just record presence/vitals ground truth
            frame = {
                "ts": time.time(),
                "label_presence": 1 if args.label != "absent" else 0,
                "label_breathing": data.get("vitals", {}).get("breathing_rate", 0),
                "label_heart":     data.get("vitals", {}).get("heart_rate", 0),
            }
            with open(output_file, "a") as f:
                f.write(json.dumps(frame) + "\n")
            frames_recorded += 1
            print(f"\r  {frames_recorded} frames recorded ({int(t_end - time.time())}s remaining)", end="", flush=True)
        except Exception as e:
            pass

    def on_error(ws, error):
        print(f"\nWS error: {error}")

    def on_close(ws, *_):
        print(f"\nDone. Recorded {frames_recorded} frames to {output_file}")

    ws_url = f"ws://{args.host}:{args.port}/ws"
    ws = websocket.WebSocketApp(ws_url, on_message=on_message,
                                on_error=on_error, on_close=on_close)
    ws.run_forever()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="RuView calibration and data collection")
    parser.add_argument("--host", default="localhost", help="Hub IP or hostname")
    parser.add_argument("--port", type=int, default=8080)

    sub = parser.add_subparsers(dest="command")

    # --empty
    sub.add_parser("empty", help="Trigger empty-room calibration baseline")

    # --test
    sub.add_parser("test", help="Show live inference output")

    # --record
    rec = sub.add_parser("record", help="Record labeled training frames")
    rec.add_argument("--label",    default="present", help="Activity label (present/absent/etc)")
    rec.add_argument("--duration", type=int, default=60, help="Recording duration in seconds")
    rec.add_argument("--output",   default=None, help="Output JSONL file path")

    args = parser.parse_args()
    if args.command == "empty":
        cmd_empty(args)
    elif args.command == "test":
        cmd_test(args)
    elif args.command == "record":
        cmd_record(args)
    else:
        parser.print_help()
