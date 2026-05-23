# Hardware Setup Guide

## Bill of Materials

| Component | Qty | Notes |
|-----------|-----|-------|
| ESP32-S3-DevKitC-1 (N8R8) | 3 | 8MB flash, 8MB PSRAM |
| Raspberry Pi Zero 2 W | 1 | 512MB RAM, quad-core Cortex-A53 |
| MicroSD card (16GB+) | 1 | Class 10 or better for Pi |
| USB-C power supply | 3 | 5V/1A per ESP32-S3 |
| USB-C/Micro-USB power for Pi | 1 | 5V/2.5A recommended |
| USB-A to USB-C cables | 3 | For flashing ESP32-S3 nodes |

## Raspberry Pi Zero 2 W Setup

### 1. Flash OS

Download [Raspberry Pi OS Lite (64-bit)](https://www.raspberrypi.com/software/) and flash with Raspberry Pi Imager.

In the imager settings, pre-configure:
- Hostname: `ruview`
- WiFi: `蝦家` (your router)
- SSH: enabled
- Username/password (your choice)

### 2. Find Pi's IP Address

```bash
# From your computer (or check your router's DHCP table)
ping ruview.local
```

Note the IP — you'll need it for the ESP32-S3 config (e.g. `192.168.1.100`).

### 3. Run Setup Script

```bash
ssh pi@ruview.local
git clone https://github.com/abiel990310/unifiedhousesystem
cd unifiedhousesystem/ruview/hub
sudo bash setup_pi.sh
```

### 4. Start the Hub

```bash
sudo systemctl start ruview
sudo journalctl -u ruview -f
```

Open `http://ruview.local:8080` in your browser — you should see the dashboard.

---

## ESP32-S3 Node Setup

### Development Environment

Install ESP-IDF v5.2+ on your computer:
```bash
# Linux/macOS
mkdir -p ~/esp
cd ~/esp
git clone --recursive https://github.com/espressif/esp-idf.git
cd esp-idf
./install.sh esp32s3
. ./export.sh
```

### Node Placement

Place nodes for maximum room coverage:

```
+--[N1]----------[N2]--+
|                       |
|         Room          |
|                       |
+-------[N3]-----------+
```

- **Node 1**: North wall, upper-left corner (or window)
- **Node 2**: North wall, upper-right corner (or doorway)
- **Node 3**: South wall, center (or opposite wall)

Nodes should be at 1–2m height, pointing toward room center.
Avoid placement inside metal cabinets or behind large appliances.

### Configure and Flash

```bash
cd ruview/firmware

# Edit config (WiFi password, Pi IP, node ID)
# Option A: menuconfig (recommended)
idf.py menuconfig
# Navigate: RuView Node Configuration

# Option B: edit main/config.h directly (for quick testing)

# Flash Node 1
./tools/flash_node.sh /dev/ttyUSB0 node_1 192.168.1.100

# Flash Node 2 (disconnect node_1, connect node_2)
./tools/flash_node.sh /dev/ttyUSB0 node_2 192.168.1.100

# Flash Node 3
./tools/flash_node.sh /dev/ttyUSB0 node_3 192.168.1.100
```

### Verify Connection

After flashing, the serial monitor (opened by flash_node.sh) should show:
```
I (1234) ruview_main: WiFi connected.
I (1456) mqtt_publish: Connected to broker 192.168.1.100:1883
I (1678) csi_capture: CSI capture started on node node_1 (channel 6)
```

On the Pi, verify MQTT messages are arriving:
```bash
mosquitto_sub -h localhost -t "ruview/#" -v
```

---

## Network Topology

```
Internet
    |
[WiFi Router 蝦家]
    |          |
    |          +-- [Raspberry Pi Zero 2 W] 192.168.1.100
    |              (MQTT broker port 1883)
    |              (Web dashboard port 8080)
    |
    +-- [ESP32-S3 node_1] 192.168.1.x
    +-- [ESP32-S3 node_2] 192.168.1.y
    +-- [ESP32-S3 node_3] 192.168.1.z
```

All devices on the same WiFi subnet. No internet required for operation.

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| Node can't connect to WiFi | Check SSID/password in config.h — Chinese SSID needs UTF-8 encoding |
| No MQTT messages on Pi | `sudo systemctl status mosquitto` — check it's running on 0.0.0.0:1883 |
| Dashboard shows "Offline" | Check `sudo systemctl status ruview` and port 8080 is reachable |
| Low CSI quality (noisy) | Move nodes away from metal surfaces; avoid 5GHz interference on channel |
| Presence stuck at 0% | Run calibration first (`/api/v1/calibrate`), then train model |
| Pi Zero 2 W too slow | Reduce `inference_rate_hz` in config.yaml from 10 to 5 |
