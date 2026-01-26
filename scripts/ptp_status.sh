#!/bin/bash

# PTP Network Status Viewer
# Usage: sudo ./ptp_status.sh

echo "========================================"
echo "    PTP Network Status Viewer"
echo "========================================"
echo ""

# Check if running as root
if [ "$EUID" -ne 0 ]; then 
    echo "Please run as root (sudo)"
    exit 1
fi

# 1. Service Status
echo "📡 PTP Service Status:"
echo "----------------------------------------"
systemctl status ptp4l-client.service --no-pager -l | grep -E "Active:|Main PID:|Tasks:"
echo ""

# 2. Current Data Set
echo "🕐 Current Time Synchronization:"
echo "----------------------------------------"
pmc -u -b 0 'GET CURRENT_DATA_SET' 2>/dev/null | grep -A5 "CURRENT_DATA_SET"
echo ""

# 3. Parent (Master) Clock Info
echo "🎯 Master Clock Information:"
echo "----------------------------------------"
pmc -u -b 0 'GET PARENT_DATA_SET' 2>/dev/null | grep -E "parentPortIdentity|grandmasterIdentity|gm.ClockClass|gm.ClockAccuracy"
# Convert parentPortIdentity to decimal
PARENT_HEX=$(pmc -u -b 0 'GET PARENT_DATA_SET' 2>/dev/null | grep "parentPortIdentity" | awk '{print $2}' | cut -d'-' -f1 | tr -d '.')
if [ -n "$PARENT_HEX" ]; then
    PARENT_DEC=$(printf "%d" 0x${PARENT_HEX} 2>/dev/null)
    echo "                parentPortIdentity (decimal)          $PARENT_DEC"
fi
# Convert grandmasterIdentity to decimal
GRANDMASTER_HEX=$(pmc -u -b 0 'GET PARENT_DATA_SET' 2>/dev/null | grep "grandmasterIdentity" | awk '{print $2}' | tr -d '.')
if [ -n "$GRANDMASTER_HEX" ]; then
    GRANDMASTER_DEC=$(printf "%d" 0x${GRANDMASTER_HEX} 2>/dev/null)
    echo "                grandmasterIdentity (decimal)         $GRANDMASTER_DEC"
fi
echo ""

# 4. Time Status
echo "⏱️  Time Status:"
echo "----------------------------------------"
pmc -u -b 0 'GET TIME_STATUS_NP' 2>/dev/null | grep -E "master_offset|gmPresent|gmIdentity"
# Convert gmIdentity to decimal
GM_HEX=$(pmc -u -b 0 'GET TIME_STATUS_NP' 2>/dev/null | grep "gmIdentity" | awk '{print $2}' | tr -d '.')
if [ -n "$GM_HEX" ]; then
    GM_DEC=$(printf "%d" 0x${GM_HEX} 2>/dev/null)
    echo "                gmIdentity (decimal)       $GM_DEC"
fi
echo ""

# 5. Port Status
echo "🔌 Port Status:"
echo "----------------------------------------"
pmc -u -b 0 'GET PORT_DATA_SET' 2>/dev/null | grep -E "portState|portIdentity"
# Convert portIdentity to decimal
PORT_HEX=$(pmc -u -b 0 'GET PORT_DATA_SET' 2>/dev/null | grep "portIdentity" | awk '{print $2}' | cut -d'-' -f1 | tr -d '.')
if [ -n "$PORT_HEX" ]; then
    PORT_DEC=$(printf "%d" 0x${PORT_HEX} 2>/dev/null)
    echo "                portIdentity (decimal)      $PORT_DEC"
fi
echo ""

# 6. Hardware Timestamping
echo "🖥️  Hardware Capabilities (eno1):"
echo "----------------------------------------"
ethtool -T eno1 2>/dev/null | grep -E "Capabilities|hardware" | head -5
echo ""

# 7. PTP Hardware Clock
echo "⏰ PTP Hardware Clock:"
echo "----------------------------------------"
if [ -e /dev/ptp0 ]; then
    phc_ctl /dev/ptp0 get 2>/dev/null | grep "clock time"
else
    echo "No PTP hardware clock found"
fi
echo ""

# 8. Recent Sync Statistics
echo "📊 Recent Sync Statistics (last 10 lines):"
echo "----------------------------------------"
journalctl -u ptp4l-client.service -n 10 --no-pager | grep "rms" | tail -5
echo ""

echo "========================================"
echo "Tip: Run 'sudo journalctl -u ptp4l-client -f' to monitor real-time logs"
echo "========================================"
