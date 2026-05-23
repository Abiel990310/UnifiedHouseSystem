#!/usr/bin/env bash
# RuView Hub — Raspberry Pi Zero 2 W setup script
# Run as root:  sudo bash setup_pi.sh
# Tested on Raspberry Pi OS Bookworm (Debian 12)

set -euo pipefail

RUVIEW_USER="ruview"
RUVIEW_DIR="/opt/ruview"
DATA_DIR="/var/lib/ruview"
LOG_DIR="/var/log/ruview"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=== RuView Hub Setup ==="
echo "Script dir: $SCRIPT_DIR"

# ── System packages ────────────────────────────────────────────────────────
echo "[1/7] Installing system packages..."
apt-get update -qq
apt-get install -y --no-install-recommends \
  python3 python3-pip python3-venv python3-full \
  python3-numpy python3-scipy \
  mosquitto mosquitto-clients \
  git curl wget

# ── Create system user ─────────────────────────────────────────────────────
echo "[2/7] Creating system user: $RUVIEW_USER"
if ! id "$RUVIEW_USER" &>/dev/null; then
  useradd -r -s /bin/false -d "$RUVIEW_DIR" "$RUVIEW_USER"
fi

# ── Directories ────────────────────────────────────────────────────────────
echo "[3/7] Creating directories..."
mkdir -p "$RUVIEW_DIR" "$DATA_DIR" "$LOG_DIR"
chown "$RUVIEW_USER:$RUVIEW_USER" "$DATA_DIR" "$LOG_DIR"

# ── Copy application files ─────────────────────────────────────────────────
echo "[4/7] Copying application files..."
# Hub source
rsync -a --delete "$SCRIPT_DIR/" "$RUVIEW_DIR/hub/"
# Dashboard
rsync -a --delete "$(dirname "$SCRIPT_DIR")/dashboard/" "$RUVIEW_DIR/dashboard/"
chown -R "$RUVIEW_USER:$RUVIEW_USER" "$RUVIEW_DIR"

# ── Python virtual environment ─────────────────────────────────────────────
echo "[5/7] Setting up Python venv..."
# --system-site-packages lets the venv use apt-installed numpy/scipy
# so we don't need to compile them from source (would take 45+ min on Pi Zero 2 W)
rm -rf "$RUVIEW_DIR/venv"
python3 -m venv --system-site-packages "$RUVIEW_DIR/venv"
"$RUVIEW_DIR/venv/bin/pip" install --upgrade pip -q
"$RUVIEW_DIR/venv/bin/pip" install -r "$RUVIEW_DIR/hub/requirements.txt" -q
echo "  venv ready: $RUVIEW_DIR/venv"

# ── Mosquitto configuration ────────────────────────────────────────────────
echo "[6/7] Configuring Mosquitto MQTT broker..."
cp "$SCRIPT_DIR/systemd/mosquitto.conf" /etc/mosquitto/conf.d/ruview.conf
systemctl enable mosquitto
systemctl restart mosquitto
echo "  Mosquitto running on port 1883"

# ── Systemd service ────────────────────────────────────────────────────────
echo "[7/7] Installing systemd service..."
cp "$SCRIPT_DIR/systemd/ruview.service" /etc/systemd/system/ruview.service

# Patch the RUVIEW_DIR path into the service file
sed -i "s|/opt/ruview|$RUVIEW_DIR|g" /etc/systemd/system/ruview.service

systemctl daemon-reload
systemctl enable ruview

echo ""
echo "=== Setup complete ==="
echo ""
echo "NEXT STEPS:"
echo "  1. Edit $RUVIEW_DIR/hub/config.yaml (set node IPs if needed)"
echo "  2. Create config.local.yaml for any overrides"
echo "  3. Start the hub:  sudo systemctl start ruview"
echo "  4. View logs:      sudo journalctl -u ruview -f"
echo "  5. Open dashboard: http://$(hostname -I | awk '{print $1}'):8080"
echo ""
echo "  Pi IP address: $(hostname -I | awk '{print $1}')"
echo "  Use this IP in ESP32-S3 config.h as RUVIEW_MQTT_BROKER_IP"
