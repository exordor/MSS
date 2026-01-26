#!/bin/bash
# Sensor Web Proxy Setup Script
# Direct port mapping for sensor web interfaces

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
CONFIG_FILE="$PROJECT_ROOT/config/sensor_proxy"
TM_PROXY_SERVICE="$PROJECT_ROOT/config/tm-proxy.service"

echo "====================================="
echo "Sensor Web Proxy Setup"
echo "====================================="
echo ""

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo "Please run this script with sudo:"
    echo "  sudo $0"
    exit 1
fi

# Get username (non-root)
REAL_USER="${SUDO_USER:-$USER}"
if [ -z "$REAL_USER" ] || [ "$REAL_USER" = "root" ]; then
    REAL_USER="eagrumo"
fi

echo "Running setup for user: $REAL_USER"
echo ""

echo "Step 1: Installing nginx and dependencies..."
apt update
apt install -y nginx python3-flup python3-requests 2>/dev/null || echo "Packages already installed"

echo ""
echo "Step 2: Adding WebSocket upgrade mapping to main nginx config..."
if ! grep -q "map \$http_upgrade \$connection_upgrade" /etc/nginx/nginx.conf; then
    sed -i '/http {/a \
\
# WebSocket connection upgrade mapping for sensor proxy\
map $http_upgrade $connection_upgrade {\
    default upgrade;\
    '"'"''"'"' close;\
}' /etc/nginx/nginx.conf
    echo "WebSocket mapping added to nginx.conf"
else
    echo "WebSocket mapping already exists"
fi

echo ""
echo "Step 3: Copying nginx configuration..."
sed -n '/# Sensor Reverse Proxy Configuration/,$p' "$CONFIG_FILE" > /etc/nginx/sites-available/sensor_proxy

echo ""
echo "Step 4: Enabling sensor_proxy site..."
ln -sf /etc/nginx/sites-available/sensor_proxy /etc/nginx/sites-enabled/sensor_proxy
rm -f /etc/nginx/sites-enabled/default

echo ""
echo "Step 5: Configuring Time Machine proxy service..."
# Update service file with correct username
sed "s/User=eagrumo/User=$REAL_USER/g; s/Group=eagrumo/Group=$REAL_USER/g" "$TM_PROXY_SERVICE" > /etc/systemd/system/tm-proxy.service

# Ask for Time Machine credentials
echo ""
echo "Time Machine Authentication Setup"
echo "==================================="
read -p "Enter Time Machine username [admin]: " TM_USER
TM_USER=${TM_USER:-admin}
read -sp "Enter Time Machine password [admin]: " TM_PASS
echo ""
TM_PASS=${TM_PASS:-admin}

# Update the service file with credentials
sed -i "s/Environment=\"TM_USERNAME=admin\"/Environment=\"TM_USERNAME=$TM_USER\"/" /etc/systemd/system/tm-proxy.service
sed -i "s/Environment=\"TM_PASSWORD=admin\"/Environment=\"TM_PASSWORD=$TM_PASS\"/" /etc/systemd/system/tm-proxy.service

echo ""
echo "Step 6: Testing nginx configuration..."
if nginx -t; then
    echo "Configuration is valid!"
else
    echo "Error: nginx configuration test failed!"
    exit 1
fi

echo ""
echo "Step 7: Starting services..."
systemctl daemon-reload
systemctl restart nginx
systemctl enable nginx
systemctl start tm-proxy
systemctl enable tm-proxy

echo ""
echo "Step 8: Configuring firewall..."
if command -v ufw &> /dev/null; then
    for port in 8080 8081 8082 8083; do
        ufw allow $port/tcp comment "Sensor proxy" 2>/dev/null
    done
    echo "Firewall rules added for ports 8080-8083"
else
    echo "Note: ufw not found, skipping firewall configuration"
fi

echo ""
echo "====================================="
echo "Setup Complete!"
echo "====================================="
echo ""
echo "Access URLs:"
echo "  Uli LiDAR:    http://<jetson-ip>:8081/"
echo "  Navi LiDAR:   http://<jetson-ip>:8082/"
echo "  Time Machine: http://<jetson-ip>:8083/"
echo "  Info:        http://<jetson-ip>:8080/"
echo ""
echo "To check status:"
echo "  sudo systemctl status nginx"
echo "  sudo systemctl status tm-proxy"
echo ""
echo "To view logs:"
echo "  sudo tail -f /var/log/nginx/uli_lidar_error.log"
echo "  sudo journalctl -u tm-proxy -f"
echo ""
