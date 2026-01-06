#!/bin/bash

# PTP Network Topology and Diagnostics
# Shows PTP network devices and their relationships

echo "========================================"
echo "   PTP Network Topology & Diagnostics"
echo "========================================"
echo ""

if [ "$EUID" -ne 0 ]; then 
    echo "Please run as root (sudo)"
    exit 1
fi

# Network Interface Info
echo "🌐 Network Interfaces with PTP Support:"
echo "----------------------------------------"
for iface in $(ls /sys/class/net/); do
    if [ -d "/sys/class/net/$iface/device" ]; then
        ts_info=$(ethtool -T $iface 2>/dev/null | grep -c "hardware")
        if [ $ts_info -gt 0 ]; then
            ip_addr=$(ip -4 addr show $iface 2>/dev/null | grep inet | awk '{print $2}')
            mac=$(ip link show $iface | grep link/ether | awk '{print $2}')
            state=$(ip link show $iface | grep -oP 'state \K\w+')
            echo "  ✓ $iface - IP: ${ip_addr:-N/A} MAC: $mac State: $state"
        fi
    fi
done
echo ""

# PTP Clocks
echo "🕐 PTP Hardware Clocks:"
echo "----------------------------------------"
for ptp in /dev/ptp*; do
    if [ -e "$ptp" ]; then
        ptp_time=$(phc_ctl $ptp get 2>/dev/null)
        echo "  $ptp: $ptp_time"
    fi
done
echo ""

# Find PTP devices on network
echo "🔍 Scanning for PTP Devices (Announce messages):"
echo "----------------------------------------"
echo "Starting 10-second capture on eno1..."
timeout 10 tcpdump -i eno1 -c 5 'ether proto 0x88f7' 2>/dev/null | grep -E "PTP|ANNOUNCE" || \
timeout 10 tcpdump -i eno1 -c 5 'udp port 319 or udp port 320' 2>/dev/null | head -10 || \
echo "No PTP traffic detected (or tcpdump not available)"
echo ""

# Show current best master
echo "👑 Best Master Clock:"
echo "----------------------------------------"
pmc -u -b 0 'GET PARENT_DATA_SET' 2>/dev/null | grep -E "grandmasterIdentity|parentPortIdentity|gm.ClockClass" | head -5
echo ""

# Show all foreign masters
echo "🌍 Foreign Masters (Discovered PTP Masters):"
echo "----------------------------------------"
journalctl -u ptp4l-client.service --no-pager | grep "foreign master" | tail -5 | \
    sed 's/.*foreign master/Foreign Master:/' || echo "No foreign masters in recent logs"
echo ""

# Clock sync path
echo "🛤️  Clock Synchronization Path:"
echo "----------------------------------------"
steps=$(pmc -u -b 0 'GET CURRENT_DATA_SET' 2>/dev/null | grep stepsRemoved | awk '{print $2}')
gm_id=$(pmc -u -b 0 'GET PARENT_DATA_SET' 2>/dev/null | grep grandmasterIdentity | tail -1 | awk '{print $2}')
local_id=$(pmc -u -b 0 'GET DEFAULT_DATA_SET' 2>/dev/null | grep clockIdentity | awk '{print $2}')

echo "  GrandMaster: $gm_id (ClockClass 6)"
echo "       ↓"
echo "  Steps: $steps hop(s)"  
echo "       ↓"
echo "  This Device: ${local_id:-Unknown}"
echo ""

# Performance metrics
echo "📈 Current Performance Metrics:"
echo "----------------------------------------"
current_data=$(pmc -u -b 0 'GET CURRENT_DATA_SET' 2>/dev/null)
offset=$(echo "$current_data" | grep offsetFromMaster | awk '{print $2}')
delay=$(echo "$current_data" | grep meanPathDelay | awk '{print $2}')
echo "  Offset from Master: ${offset} ns"
echo "  Mean Path Delay: ${delay} ns"
echo ""

# Port Statistics
echo "📊 Port Statistics:"
echo "----------------------------------------"
pmc -u -b 0 'GET PORT_STATS_NP' 2>/dev/null | grep -E "portIdentity|rxMsgType|txMsgType" | head -20 || \
echo "Port statistics not available"
echo ""

echo "========================================"
