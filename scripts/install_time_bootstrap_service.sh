#!/bin/bash

set -euo pipefail

SERVICE_PATH="/etc/systemd/system/time-bootstrap.service"

if [ "$EUID" -ne 0 ]; then
  echo "This installer uses sudo for systemd changes."
fi

sudo tee "$SERVICE_PATH" >/dev/null <<'EOF'
[Unit]
Description=Bootstrap time via Chrony then switch to PTP
Wants=network-online.target
After=network-online.target

[Service]
Type=oneshot
EnvironmentFile=-/etc/default/time-bootstrap
ExecStart=/home/eagrumo/mss_lecture/scripts/time_bootstrap.sh
StandardOutput=append:/home/eagrumo/mss_lecture/logs/time-bootstrap.log
StandardError=append:/home/eagrumo/mss_lecture/logs/time-bootstrap.log
TimeoutStartSec=3700
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload

# Remove previous ordering overrides to avoid deadlock
sudo rm -f /etc/systemd/system/ptp4l-client.service.d/override.conf
sudo rm -f /etc/systemd/system/phc2sys-client.service.d/override.conf
sudo rmdir --ignore-fail-on-non-empty /etc/systemd/system/ptp4l-client.service.d 2>/dev/null || true
sudo rmdir --ignore-fail-on-non-empty /etc/systemd/system/phc2sys-client.service.d 2>/dev/null || true

sudo systemctl daemon-reload
sudo systemctl enable time-bootstrap.service
sudo systemctl restart time-bootstrap.service

echo "Installed and started time-bootstrap.service (ordering overrides removed)"
