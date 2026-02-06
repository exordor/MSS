#!/bin/bash

set -euo pipefail

TM_IP="${TM_IP:-192.168.0.20}"
PTP_DEV="${PTP_DEV:-/dev/ptp0}"
IFACE="${IFACE:-eno1}"
TIMEOUT="${TIMEOUT:-240}"
INTERVAL="${INTERVAL:-2}"
LOG_FILE="${LOG_FILE:-/home/eagrumo/mss_lecture/logs/time-bootstrap.log}"

log() {
  local ts
  ts="$(date '+%Y-%m-%d %H:%M:%S')"
  echo "[$ts] [time-bootstrap] $*" | tee -a "$LOG_FILE"
}

if [ "$EUID" -ne 0 ]; then
  log "Please run as root (sudo)"
  exit 1
fi

mkdir -p "$(dirname "$LOG_FILE")"

for cmd in chronyc systemctl; do
  if ! command -v "$cmd" >/dev/null 2>&1; then
    log "Missing required command: $cmd"
    exit 1
  fi
done

log "Stopping ptp4l/phc2sys to avoid conflicts during NTP bootstrap..."
systemctl stop ptp4l-client.service >/dev/null 2>&1 || true
systemctl stop phc2sys-client.service >/dev/null 2>&1 || true

log "Stopping systemd-timesyncd to avoid conflicts with chrony..."
systemctl stop systemd-timesyncd.service >/dev/null 2>&1 || true

if command -v rg >/dev/null 2>&1; then
  has_server=$(rg -q "server\\s+${TM_IP}\\b" /etc/chrony/chrony.conf && echo yes || echo no)
else
  has_server=$(grep -Eq "server[[:space:]]+${TM_IP}\\b" /etc/chrony/chrony.conf && echo yes || echo no)
fi

if [ "$has_server" = "no" ]; then
  log "Adding TimeMachine NTP server to /etc/chrony/chrony.conf: ${TM_IP}"
  echo "server ${TM_IP} iburst prefer" >> /etc/chrony/chrony.conf
fi

log "Starting chrony..."
systemctl start chrony

deadline=$(( $(date +%s) + TIMEOUT ))
synced=false

log "Waiting for chrony sync (timeout=${TIMEOUT}s)..."
while [ "$(date +%s)" -lt "$deadline" ]; do
  tracking="$(chronyc tracking 2>/dev/null || true)"
  leap="$(echo "$tracking" | awk -F': ' '/Leap status/ {print $2; exit}')"
  refid="$(echo "$tracking" | awk -F': ' '/Reference ID/ {print $2; exit}')"
  stratum="$(echo "$tracking" | awk -F': ' '/Stratum/ {print $2; exit}')"

  # Strict success criteria:
  # - Leap status indicates synchronized
  # - Reference ID is not 00000000
  # - Stratum is > 0
  if { [ "$leap" = "Normal" ] || [ "$leap" = "Insert second" ] || [ "$leap" = "Delete second" ]; } \
     && [ -n "$refid" ] && [ "${refid%% *}" != "00000000" ] \
     && [ -n "$stratum" ] && [ "$stratum" -gt 0 ] 2>/dev/null; then
    synced=true
    break
  fi

  sleep "$INTERVAL"
done

if ! $synced; then
  log "Chrony sync timeout. Proceeding anyway to PTP."
else
  log "Chrony synchronized."
fi

if [ -e "$PTP_DEV" ] && command -v phc_ctl >/dev/null 2>&1; then
  log "Setting PHC from system time: ${PTP_DEV}"
  phc_ctl "$PTP_DEV" set >/dev/null 2>&1 || true
fi

log "Stopping chrony to avoid conflict with PTP..."
systemctl stop chrony >/dev/null 2>&1 || true

log "Starting ptp4l and phc2sys..."
systemctl start ptp4l-client.service >/dev/null 2>&1 || true
systemctl start phc2sys-client.service >/dev/null 2>&1 || true

if [ -x /home/eagrumo/mss_lecture/scripts/ptp_wait_master_check.sh ]; then
  log "Waiting for PTP master and checking PHC..."
  /home/eagrumo/mss_lecture/scripts/ptp_wait_master_check.sh -i "$IFACE" -d "$PTP_DEV" -t "$TIMEOUT" -p "$INTERVAL" || true
fi

log "Done."
