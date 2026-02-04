#!/usr/bin/env bash
set -euo pipefail

# Simple TigerVNC launcher with defaults and idempotent behavior.
DISPLAY_NUM=${1:-2}
GEOMETRY=${2:-1920x1080}
LOCALHOST=${3:-no}

# If already running on this display, exit gracefully.
if pgrep -f "Xtigervnc.*:${DISPLAY_NUM}" >/dev/null; then
  echo "TigerVNC already running on :${DISPLAY_NUM}" >&2
  exit 0
fi

vncserver ":${DISPLAY_NUM}" -geometry "${GEOMETRY}" -localhost "${LOCALHOST}"

echo "Started TigerVNC on :${DISPLAY_NUM} (port $((5900 + DISPLAY_NUM)))"
