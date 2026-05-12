#!/bin/bash
# InductIQ Platform - Installation Script
# Target: Raspberry Pi 3B+ running Raspberry Pi OS Lite (64-bit)
set -euo pipefail

INSTALL_DIR="/opt/edge-ai"
DATA_DIR="/var/lib/edge-ai"
LOG_DIR="/var/log/edge-ai"
CONFIG_DIR="/etc/edge-ai"
SERVICE_USER="edgeai"

echo "============================================"
echo "  InductIQ Platform Installer"
echo "  Target: Raspberry Pi 3B+"
echo "============================================"

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo "ERROR: Please run as root (sudo)"
    exit 1
fi

# Check architecture
ARCH=$(uname -m)
if [[ "$ARCH" != "aarch64" && "$ARCH" != "armv7l" ]]; then
    echo "WARNING: Expected ARM architecture, got $ARCH"
fi

echo "[1/8] Installing system dependencies..."
apt-get update -qq
apt-get install -y -qq \
    python3.11 \
    python3.11-venv \
    python3.11-dev \
    mosquitto \
    mosquitto-clients \
    libatlas-base-dev \
    libopenblas-dev \
    build-essential

echo "[2/8] Creating service user..."
if ! id "$SERVICE_USER" &>/dev/null; then
    useradd --system --shell /bin/false --home-dir "$INSTALL_DIR" "$SERVICE_USER"
fi

echo "[3/8] Creating directories..."
mkdir -p "$INSTALL_DIR"
mkdir -p "$DATA_DIR"/{models,archives/telemetry,archives/inference}
mkdir -p "$LOG_DIR"
mkdir -p "$CONFIG_DIR"

echo "[4/8] Setting up Python virtual environment..."
python3.11 -m venv "$INSTALL_DIR/.venv"
source "$INSTALL_DIR/.venv/bin/activate"

echo "[5/8] Installing Python packages..."
pip install --upgrade pip wheel setuptools
pip install -r "$INSTALL_DIR/requirements.txt"

echo "[6/8] Configuring Mosquitto..."
cp "$INSTALL_DIR/config/mosquitto.conf" /etc/mosquitto/conf.d/edge-ai.conf
# Create password file
mosquitto_passwd -c -b /etc/mosquitto/passwd edgeai edgeai2024
systemctl restart mosquitto

echo "[7/8] Installing systemd services..."
cp "$INSTALL_DIR/deploy/systemd/edge-platform.service" /etc/systemd/system/
cp "$INSTALL_DIR/deploy/systemd/edge-archiver.service" /etc/systemd/system/
cp "$INSTALL_DIR/deploy/systemd/edge-archiver.timer" /etc/systemd/system/

# Copy config
cp "$INSTALL_DIR/config/platform.yaml" "$CONFIG_DIR/platform.yaml"

echo "[8/8] Setting permissions..."
chown -R "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR"
chown -R "$SERVICE_USER:$SERVICE_USER" "$DATA_DIR"
chown -R "$SERVICE_USER:$SERVICE_USER" "$LOG_DIR"
chmod 750 "$DATA_DIR"
chmod 750 "$LOG_DIR"

# Enable services
systemctl daemon-reload
systemctl enable edge-platform.service
systemctl enable edge-archiver.timer

echo ""
echo "============================================"
echo "  Installation Complete!"
echo "============================================"
echo ""
echo "  Start the platform:"
echo "    sudo systemctl start edge-platform"
echo ""
echo "  View logs:"
echo "    journalctl -u edge-platform -f"
echo ""
echo "  Dashboard:"
echo "    http://$(hostname -I | awk '{print $1}'):8420"
echo ""
echo "  MQTT Broker:"
echo "    localhost:1883"
echo ""
echo "  API Docs:"
echo "    http://$(hostname -I | awk '{print $1}'):8420/api/docs"
echo ""
