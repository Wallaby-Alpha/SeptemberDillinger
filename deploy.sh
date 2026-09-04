#!/usr/bin/env bash
# ==============================================================================
# Automated Deployment Script for DigitalOcean Droplet (Ubuntu / Debian)
# MEXC Quiet Accumulation Scanner
# ==============================================================================

set -e

APP_DIR="/opt/mexc-accumulation-scanner"
SERVICE_NAME="mexc-scanner"

echo "=========================================================="
echo "🚀 Deploying MEXC Quiet Accumulation Scanner to Droplet"
echo "=========================================================="

# 1. Update and install system dependencies
echo "📦 Installing system dependencies (Python3, Venv, SQLite)..."
sudo apt-get update -y
sudo apt-get install -y python3 python3-pip python3-venv git sqlite3

# 2. Setup App Directory
if [ "$PWD" != "$APP_DIR" ]; then
    echo "📁 Copying application to $APP_DIR..."
    sudo mkdir -p "$APP_DIR"
    sudo cp -r . "$APP_DIR"
    cd "$APP_DIR"
fi

# 3. Setup Python Virtual Environment
echo "🐍 Setting up Python virtual environment..."
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# 4. Check for .env or config.json
if [ ! -f "config.json" ] && [ ! -f ".env" ]; then
    echo "⚠️  No config.json or .env detected."
    echo "📝 Creating .env from .env.example..."
    cp .env.example .env
    echo "--------------------------------------------------------"
    echo "❗ ACTION REQUIRED: Please edit .env with your Telegram tokens:"
    echo "   nano $APP_DIR/.env"
    echo "--------------------------------------------------------"
fi

# 5. Install Systemd Service
echo "⚙️  Configuring Systemd service..."
sudo cp mexc-scanner.service /etc/systemd/system/${SERVICE_NAME}.service
sudo systemctl daemon-reload
sudo systemctl enable ${SERVICE_NAME}
sudo systemctl restart ${SERVICE_NAME}

echo "=========================================================="
echo "✅ Deployment Complete!"
echo "• Service Status: sudo systemctl status ${SERVICE_NAME}"
echo "• View Live Logs: sudo journalctl -u ${SERVICE_NAME} -f"
echo "• Stop Scanner:   sudo systemctl stop ${SERVICE_NAME}"
echo "• Restart:        sudo systemctl restart ${SERVICE_NAME}"
echo "• Run Performance Matrix: $APP_DIR/.venv/bin/python performance_tracker.py"
echo "=========================================================="
