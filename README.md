# UnifiedHouseSystem

A modular, extensible house intelligence platform built on WiFi CSI sensing.

## Modules

| Module | Description | Status |
|--------|-------------|--------|
| **RuView** | WiFi CSI person tracking — presence, pose, vitals | Active |
| Lighting | Smart light control | Planned |
| Climate | HVAC / thermostat control | Planned |
| Security | Door/window sensors, alerts | Planned |
| Energy | Power monitoring & automation | Planned |

## Hardware

- **3x ESP32-S3** — CSI sensor nodes (WiFi CSI capture + edge preprocessing)
- **1x Raspberry Pi Zero 2 W** — Central hub (MQTT broker + AI inference + REST API)
- **WiFi Router** — SSID: `蝦家` (existing infrastructure)

## Quick Start

### 1. Flash ESP32-S3 Nodes

```bash
cd ruview/firmware
# Edit main/config.h — set WIFI_SSID, WIFI_PASS, MQTT_BROKER_IP, NODE_ID
idf.py set-target esp32s3
idf.py build
./tools/flash_node.sh /dev/ttyUSB0 node_1
```

### 2. Set Up Raspberry Pi Hub

```bash
cd ruview/hub
sudo bash setup_pi.sh
sudo systemctl start ruview
```

### 3. Access Dashboard

Open `http://<pi-ip>:8080` in your browser.

API docs: `http://<pi-ip>:8080/api/docs`

## Architecture

```
WiFi Router (蝦家)
  ESP32-S3 Node 1 -- MQTT -->|
  ESP32-S3 Node 2 -- MQTT -->|---> Pi Zero 2 W (Hub)
  ESP32-S3 Node 3 -- MQTT -->|          |
                                         +-- Mosquitto MQTT Broker
                                         +-- RuVector Inference (numpy)
                                         +-- FastAPI REST + WebSocket
                                         +-- Web Dashboard --> Browser
```

### Signal Pipeline

```
Router beacon/probe packets
  -> ESP32-S3 captures WiFi CSI (56 subcarriers x 3 nodes)
  -> FFT amplitude + phase extraction per node
  -> MQTT publish to Pi (JSON, ~10 Hz)
  -> Pi fuses 3-node features -> [30-frame window, 168 features]
  -> RuVector model -> presence + 17-joint pose + vitals
  -> FastAPI /api/v1/* + WebSocket broadcast
```

## API Overview

```
GET  /api/v1/presence      Person detection (confidence, count, zone)
GET  /api/v1/pose          17-joint skeleton pose
GET  /api/v1/vitals        Breathing rate + heart rate
GET  /api/v1/nodes         Node health and CSI statistics
GET  /api/v1/system        Hub status, uptime, inference stats
POST /api/v1/calibrate     Trigger room calibration (empty-room baseline)
WS   /ws                   Real-time stream of all outputs
```

## Core Platform

`core/` contains the Unified House System foundation — event bus, module registry,
and base module class that all future house modules plug into.

## Documentation

- [Hardware Setup Guide](docs/hardware_setup.md)
- [Architecture Deep Dive](docs/architecture.md)
- [API Reference](docs/api_reference.md)
- [Model Training Guide](docs/model_training.md)
