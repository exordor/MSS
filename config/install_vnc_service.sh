#!/bin/bash
# Install VNC Server service and enable auto-start on boot

set -e

SERVICE_NAME="vncserver"
SERVICE_FILE="/home/eagrumo/mss_lecture/config/${SERVICE_NAME}@.service"
SYSTEMD_DIR="/etc/systemd/system"
TARGET_USER="eagrumo"
TARGET_HOME="/home/eagrumo"

echo "=== Installing ${SERVICE_NAME} service ==="

# Check if service file exists
if [ ! -f "$SERVICE_FILE" ]; then
    echo "Error: Service file not found: $SERVICE_FILE"
    exit 1
fi

# Check if VNC is installed
if ! command -v vncserver &> /dev/null; then
    echo "Error: VNC Server not installed"
    echo "Please run first: sudo apt install tigervnc-standalone-server xfce4 -y"
    exit 1
fi

# Check xstartup configuration
if [ ! -f "$TARGET_HOME/.vnc/xstartup" ]; then
    echo "Warning: xstartup config not found, creating..."
    mkdir -p "$TARGET_HOME/.vnc"
    cat > "$TARGET_HOME/.vnc/xstartup" << 'EOF'
#!/bin/bash
unset SESSION_MANAGER
unset DBUS_SESSION_BUS_ADDRESS
exec startxfce4
EOF
    chmod +x "$TARGET_HOME/.vnc/xstartup"
    echo "Created xstartup configuration"
fi

# Check VNC password
if [ ! -f "$TARGET_HOME/.vnc/passwd" ]; then
    echo "Warning: VNC password not set, please run: vncpasswd"
    exit 1
fi

# Stop existing service if running
DISPLAY_NUM="2"
SERVICE_INSTANCE="${SERVICE_NAME}@${DISPLAY_NUM}.service"
if systemctl is-active --quiet "$SERVICE_INSTANCE"; then
    echo "Stopping running service..."
    sudo systemctl stop "$SERVICE_INSTANCE"
fi

# Copy service file to systemd directory
echo "Installing service file to $SYSTEMD_DIR..."
sudo cp "$SERVICE_FILE" "$SYSTEMD_DIR/"

# Reload systemd configuration
echo "Reloading systemd configuration..."
sudo systemctl daemon-reload

# Enable auto-start on boot
echo "Enabling ${SERVICE_NAME} auto-start (Display :${DISPLAY_NUM})..."
sudo systemctl enable "$SERVICE_INSTANCE"

# Start service
echo "Starting ${SERVICE_NAME} service..."
sudo systemctl start "$SERVICE_INSTANCE"

# Wait for service to start
sleep 3

# Show service status
echo ""
echo "=== Service Status ==="
sudo systemctl status "$SERVICE_INSTANCE" --no-pager

echo ""
echo "=== Installation Complete ==="
echo "Service enabled for auto-start on boot"
echo ""
echo "Connection Info:"
ip addr show | grep "inet " | grep -v 127.0.0.1 | awk '{print "  IP: " $2}' | sed 's/\/.*//'
echo "  Port: 590${DISPLAY_NUM}"
echo ""
echo "Common Commands:"
echo "  Status:   sudo systemctl status $SERVICE_INSTANCE"
echo "  Start:    sudo systemctl start $SERVICE_INSTANCE"
echo "  Stop:     sudo systemctl stop $SERVICE_INSTANCE"
echo "  Restart:  sudo systemctl restart $SERVICE_INSTANCE"
echo "  Logs:     sudo journalctl -u $SERVICE_INSTANCE -f"
