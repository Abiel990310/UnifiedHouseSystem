# Architecture Deep Dive

## System Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                      WiFi Router (蝦家)                          │
└────────────┬──────────────┬──────────────┬──────────────────────┘
             │              │              │
    ┌────────┴─┐    ┌───────┴──┐   ┌───────┴──┐
    │ ESP32-S3 │    │ ESP32-S3 │   │ ESP32-S3 │
    │  node_1  │    │  node_2  │   │  node_3  │
    │ N.wall   │    │ E.wall   │   │ S.wall   │
    └────┬─────┘    └────┬─────┘   └────┬─────┘
         │  MQTT/JSON    │              │
         └───────────────┴──────────────┘
                         │
              ┌──────────┴──────────────────────────┐
              │       Raspberry Pi Zero 2 W          │
              │                                      │
              │  ┌─────────────────────────────┐     │
              │  │   Mosquitto MQTT Broker      │     │
              │  │   port 1883                  │     │
              │  └──────────┬──────────────────┘     │
              │             │                        │
              │  ┌──────────▼──────────────────┐     │
              │  │   SystemState (in-memory)    │     │
              │  │   - per-node CSI ring buffer │     │
              │  └──────────┬──────────────────┘     │
              │             │                        │
              │  ┌──────────▼──────────────────┐     │
              │  │   InferencePipeline (10Hz)   │     │
              │  │   fusion → RuVector → vitals │     │
              │  └──────────┬──────────────────┘     │
              │             │                        │
              │  ┌──────────▼──────────────────┐     │
              │  │   FastAPI + WebSocket        │     │
              │  │   port 8080                  │     │
              │  └──────────┬──────────────────┘     │
              │             │                        │
              │  ┌──────────▼──────────────────┐     │
              │  │   SQLite Database            │     │
              │  │   /var/lib/ruview/ruview.db  │     │
              │  └─────────────────────────────┘     │
              └──────────────────────────────────────┘
                             │
                    ┌────────▼───────┐
                    │  Web Browser   │
                    │  Dashboard     │
                    └────────────────┘
```

## ESP32-S3 Firmware Pipeline

```
WiFi packets (AP beacons, ACKs, data frames from router)
    │
    ▼
esp_wifi_set_csi_rx_cb()          ← hardware CSI callback
    │
    ▼  csi_capture.c
Raw IQ data [int8 pairs × 64 subcarriers]
    │
    ▼
Subcarrier selection              ← 56 usable out of 64 (remove DC + guard)
    │
    ▼
Amplitude = sqrt(real² + imag²)   ← per subcarrier
Phase     = atan2(imag, real)
    │
    ▼
Moving average smoothing          ← 5-frame window per subcarrier
    │
    ▼
Motion variance                   ← mean(Amp²) - mean(Amp)²
    │
    ▼
FreeRTOS queue                    ← ISR-safe, depth 8
    │
    ▼  mqtt_publish_task (10Hz, core 1)
JSON serialization                ← ~800 bytes per frame
{"n":"node_1","t":...,"a":[...],"p":[...],"mv":...,"r":-55,"ch":6}
    │
    ▼
esp_mqtt_client_publish()         ← QoS 0 (UDP-like, max throughput)
Topic: ruview/node/node_1/csi
```

## Pi Hub Signal Pipeline

```
MQTT subscriber (aiomqtt)
    │
    ▼  SystemState.update_node_csi()
Per-node ring buffer [30 frames × 56 subcarriers]
    │
    ▼  InferencePipeline._step()  (10Hz)
fuse_nodes()
    - Reshape: [30, 3×56]  →  [30, 3, 56]
    - Differential CSI: subtract baseline
    - Per-node L2 normalization
    - Node weight scaling
    - Hampel outlier clamping (3σ)
    Output: [30, 168]
    │
    ▼  RuVectorModel.infer()
Input projection [30, 168]
    │
Conv1D k=5: [30, 168] → [26, 32]  (temporal features)
    │
Conv1D k=3: [26, 32]  → [24, 64]  (higher-level features)
    │
Self-attention: [24, 64] → [24, 64]  (focus on motion events)
    │
Residual + LayerNorm
    │
Temporal mean pooling: [24, 64] → [64]
    │
Linear projection: [64] → [128]    (environment fingerprint)
    │
    ├── presence_head: [128] → sigmoid → confidence
    ├── pose_head:     [128] → sigmoid×17×3 → joint positions
    └── vitals_head:   [128] → sigmoid×2 → (br_norm, hr_norm)
    │
    ▼  VitalsExtractor (FFT on long buffer)
Motion variance time series (30–60s)
    │
FFT peak picking in physiological bands:
    - Breathing: 0.1–0.5 Hz (6–30 breaths/min)
    - Heart rate: 0.8–3.0 Hz (48–180 bpm)
```

## RuVector Model (~55K parameters)

| Layer | Shape | Params |
|-------|-------|--------|
| Conv1D-1 (k=5) | [5, 168, 32] + bias | 26,912 |
| Conv1D-2 (k=3) | [3, 32, 64] + bias | 6,208 |
| Attention Wq/Wk/Wv/Wo | [64, 64] × 4 | 16,384 |
| Projection W | [64, 128] + bias | 8,320 |
| Presence head | [128, 1] + bias | 129 |
| Pose head | [128, 51] + bias | 6,579 |
| Vitals head | [128, 2] + bias | 258 |
| **Total** | | **~64,790** |

## Unified House System Architecture

The `core/` module provides the platform foundation all future modules use:

```python
core/
  EventBus      # Async pub/sub with MQTT-style wildcards
  BaseModule    # Abstract base — start/stop lifecycle + event helpers
  ModuleRegistry # Tracks all active modules, health checks, ordered shutdown
  CoreConfig    # Shared platform config
```

Future modules (lighting, climate, security) will:
1. Subclass `BaseModule`
2. Subscribe to `ruview/#` events for automation triggers
   - e.g. `ruview/system/presence` → turn on lights when person enters
3. Publish their own events to the bus
4. Register with `ModuleRegistry`

## API Design

Versioned REST API with extensible namespace:

```
/api/v1/*          RuView endpoints (current)
/api/v2/*          Reserved for future modules / aggregated endpoints
/api/docs          OpenAPI/Swagger UI
/ws                WebSocket (10Hz real-time stream)
```

## Data Flow Latency Budget (Pi Zero 2 W)

| Stage | Latency |
|-------|---------|
| ESP32-S3 CSI capture | ~1ms |
| ESP32-S3 JSON encode | ~2ms |
| WiFi → MQTT broker | ~5ms (LAN) |
| Python MQTT dispatch | ~1ms |
| Ring buffer write | <0.1ms |
| Inference (numpy) | ~10–20ms |
| WebSocket broadcast | ~1ms |
| **End-to-end** | **~20–30ms** |
