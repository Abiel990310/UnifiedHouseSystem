#!/usr/bin/env bash
# Flash RuView firmware to an ESP32-S3 node.
# Usage: ./flash_node.sh <port> <node_id> [<mqtt_broker_ip>]
#
# Example:
#   ./flash_node.sh /dev/ttyUSB0 node_1 192.168.1.100
#   ./flash_node.sh /dev/ttyACM0 node_2

set -euo pipefail

PORT="${1:-/dev/ttyUSB0}"
NODE_ID="${2:-node_1}"
BROKER_IP="${3:-192.168.1.100}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FW_DIR="$(dirname "$SCRIPT_DIR")"

echo "=== RuView Firmware Flash ==="
echo "  Port:      $PORT"
echo "  Node ID:   $NODE_ID"
echo "  Broker IP: $BROKER_IP"
echo "  FW dir:    $FW_DIR"
echo ""

# Check IDF is available
if [ -z "${IDF_PATH:-}" ]; then
  echo "ERROR: IDF_PATH not set. Source ESP-IDF first:"
  echo "  . ~/esp/esp-idf/export.sh"
  exit 1
fi

cd "$FW_DIR"

# Configure via sdkconfig overrides (avoids modifying Kconfig or source)
echo "[1/3] Setting node-specific config..."
cat > sdkconfig.node_override << EOF
CONFIG_RUVIEW_NODE_ID="$NODE_ID"
CONFIG_RUVIEW_MQTT_BROKER_IP="$BROKER_IP"
EOF

# Build (merges sdkconfig.defaults + sdkconfig.node_override)
echo "[2/3] Building firmware for $NODE_ID..."
idf.py \
  -DSDKCONFIG_DEFAULTS="sdkconfig.defaults;sdkconfig.node_override" \
  set-target esp32s3 \
  build

# Flash + monitor
echo "[3/3] Flashing to $PORT..."
idf.py \
  -p "$PORT" \
  -b 921600 \
  flash monitor

rm -f sdkconfig.node_override
