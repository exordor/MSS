#!/bin/bash
# Install ros2-diagnostic service and enable it on boot

set -e

SERVICE_NAME="ros2-diagnostic"
SERVICE_FILE="/home/eagrumo/mss_lecture/config/${SERVICE_NAME}.service"
SYSTEMD_DIR="/etc/systemd/system"

echo "=== Installing ${SERVICE_NAME} service ==="

# Check if service file exists
if [ ! -f "$SERVICE_FILE" ]; then
    echo "Error: Service file not found: $SERVICE_FILE"
    exit 1
fi

# Check if Python main script exists
MAIN_PY="/home/eagrumo/mss_lecture/ros2_diagnostic/main.py"
if [ ! -f "$MAIN_PY" ]; then
    echo "Error: Main script not found: $MAIN_PY"
    exit 1
fi

# Stop existing service (if running)
if systemctl is-active --quiet "$SERVICE_NAME"; then
    echo "Stopping running service..."
    sudo systemctl stop "$SERVICE_NAME"
fi

# Copy service file to systemd directory
echo "Installing service file to $SYSTEMD_DIR..."
sudo cp "$SERVICE_FILE" "$SYSTEMD_DIR/"

# Reload systemd configuration
echo "Reloading systemd configuration..."
sudo systemctl daemon-reload

# Enable service on boot
echo "Enabling ${SERVICE_NAME} on boot..."
sudo systemctl enable "$SERVICE_NAME"

# Start service
echo "Starting ${SERVICE_NAME} service..."
sudo systemctl start "$SERVICE_NAME"

# Wait for service to start
sleep 2

# Show service status
echo ""
echo "=== Service Status ==="
sudo systemctl status "$SERVICE_NAME" --no-pager

echo ""
echo "=== Installation Complete ==="
echo "Service has been enabled for auto-start on boot"
echo ""
echo "Useful commands:"
echo "  Check status:  sudo systemctl status $SERVICE_NAME"
echo "  Start service: sudo systemctl start $SERVICE_NAME"
echo "  Stop service:  sudo systemctl stop $SERVICE_NAME"
echo "  Restart service: sudo systemctl restart $SERVICE_NAME"
echo "  View logs:     sudo journalctl -u $SERVICE_NAME -f"
