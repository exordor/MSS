#!/bin/bash

# PTP System Clock Sync Verification Script
# Verify if phc2sys correctly synchronizes PTP time to system clock
# Usage: sudo ./ptp_sync_verify.sh

echo "========================================"
echo "  PTP System Clock Sync Verification"
echo "========================================"
echo ""

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo "⚠️  Please run as root (sudo)"
    exit 1
fi

INTERFACE="eno1"
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 1. Service Status Check
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "📡 1. Service Status Check"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# phc2sys status
echo -n "phc2sys-client.service:   "
if systemctl is-active --quiet phc2sys-client.service; then
    echo -e "${GREEN}✓ Running${NC}"
    systemctl status phc2sys-client.service --no-pager | grep "Active:" | head -1
else
    echo -e "${RED}✗ Not Running${NC}"
fi
echo ""

# systemd-timesyncd status
echo -n "systemd-timesyncd:      "
if systemctl is-active --quiet systemd-timesyncd.service; then
    echo -e "${YELLOW}⚠ Running (should be stopped for pure PTP)${NC}"
    systemctl status systemd-timesyncd.service --no-pager | grep "Active:" | head -1
else
    echo -e "${GREEN}✓ Stopped (correct for PTP)${NC}"
fi
echo ""

# timedatectl status
echo "timedatectl status:"
timedatectl status | grep -E "NTP service|System clock synchronized"
echo ""

# 2. phc2sys Logs
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "📋 2. Recent phc2sys Logs"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
journalctl -u phc2sys-client.service --no-pager --no-pager -n 5 | grep -v "^--"
echo ""

# 3. Clock Comparison
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "⏱️  3. Clock Comparison (PHC vs System)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo -e "${YELLOW}Note: Results are for reference only. Check ptp4l and phc2sys logs for actual sync status.${NC}"
echo ""

# Get time properties (UTC offset, timescale)
TIME_PROP=$(pmc -u -b 0 'GET TIME_PROPERTIES_DATA_SET' 2>/dev/null)
UTC_OFFSET=$(echo "$TIME_PROP" | awk '/currentUtcOffset[[:space:]]/{print $2}')
UTC_OFFSET_VALID=$(echo "$TIME_PROP" | awk '/currentUtcOffsetValid[[:space:]]/{print $2}')
PTP_TIMESCALE=$(echo "$TIME_PROP" | awk '/ptpTimescale[[:space:]]/{print $2}')

# Get PHC time (raw TAI time, no conversion)
PHC_DEVICE="/dev/ptp0"
PHC_TIME=$(phc_ctl $PHC_DEVICE get 2>/dev/null | sed -n 's/.*clock time is \([0-9]\+\(\.[0-9]\+\)\?\).*/\1/p')

# Get System time once (CLOCK_REALTIME - timescale depends on sync strategy)
SYS_SEC=$(date +%s)
SYS_NSEC=$(date +%N)
SYS_TIME=$(date -d "@$SYS_SEC" +"%Y-%m-%d %H:%M:%S").$SYS_NSEC

if [ -z "$PHC_TIME" ]; then
    PHC_TIME="N/A"
fi

if [ "$PHC_TIME" != "N/A" ]; then
    PHC_SEC="${PHC_TIME%%.*}"
    PHC_NSEC="${PHC_TIME#*.}"
    if [ "$PHC_TIME" = "$PHC_SEC" ]; then
        PHC_NSEC="000000000"
    fi
    # Display PHC time as-is (TAI time)
    if PHC_DATE=$(date -d "@$PHC_SEC" +"%Y-%m-%d %H:%M:%S" 2>/dev/null); then
        echo "PHC Time (${PHC_DEVICE}):        $PHC_DATE.$PHC_NSEC (TAI)"
    else
        echo -e "${RED}PHC Time (${PHC_DEVICE}):        Invalid value ($PHC_TIME)${NC}"
    fi
    if [ "$PTP_TIMESCALE" = "1" ] && [ "$UTC_OFFSET_VALID" = "1" ] && [ -n "$UTC_OFFSET" ]; then
        PHC_UTC_SEC=$((PHC_SEC - UTC_OFFSET))
        if PHC_UTC_DATE=$(date -d "@$PHC_UTC_SEC" +"%Y-%m-%d %H:%M:%S" 2>/dev/null); then
            echo "PHC Time (UTC):          $PHC_UTC_DATE.$PHC_NSEC (TAI-$UTC_OFFSET)"
        fi
        echo -e "                        ${YELLOW}(PTP timescale=TAI, UTC offset=${UTC_OFFSET}s; diff ≈ ${UTC_OFFSET}s if system is UTC)${NC}"
    else
        echo -e "                        ${YELLOW}(PTP timescale/UTC offset not available)${NC}"
    fi
else
    echo -e "${RED}PHC Time (${PHC_DEVICE}):        Cannot read${NC}"
fi

echo "System Time:            $SYS_TIME (CLOCK_REALTIME)"

# Display raw timestamps for comparison
if [ "$PHC_TIME" != "N/A" ]; then
    # Compute PHC - System difference
    PHC_NSEC_INT=$((10#$PHC_NSEC))
    SYS_NSEC_INT=$((10#$SYS_NSEC))
    DIFF_NS=$(((PHC_SEC - SYS_SEC) * 1000000000 + (PHC_NSEC_INT - SYS_NSEC_INT)))
    if [ $DIFF_NS -lt 0 ]; then
        DIFF_ABS=$(( -DIFF_NS ))
    else
        DIFF_ABS=$DIFF_NS
    fi
    DIFF_SEC=$(awk "BEGIN{printf \"%.6f\", $DIFF_NS/1000000000}")
    echo ""
    echo "PHC - System:           ${DIFF_SEC} s"

    if [ "$PTP_TIMESCALE" = "1" ] && [ "$UTC_OFFSET_VALID" = "1" ] && [ -n "$UTC_OFFSET" ]; then
        OFFSET_NS=$((UTC_OFFSET * 1000000000))
        OFFSET_NS_MIN=$((OFFSET_NS - 1000000000))
        OFFSET_NS_MAX=$((OFFSET_NS + 1000000000))
        if [ $DIFF_ABS -le 1000000000 ]; then
            echo -e "Inference:              ${GREEN}System time appears TAI (PHC≈System)${NC}"
        elif [ $DIFF_ABS -ge $OFFSET_NS_MIN ] && [ $DIFF_ABS -le $OFFSET_NS_MAX ]; then
            echo -e "Inference:              ${GREEN}System time appears UTC (PHC≈UTC+${UTC_OFFSET}s)${NC}"
        else
            echo -e "Inference:              ${YELLOW}System time scale unclear (diff not ~0s or ~${UTC_OFFSET}s)${NC}"
        fi
    fi

    echo ""
    echo "Raw Timestamps:"
    echo "  PHC (TAI):             $PHC_TIME"
    echo "  System (UTC):          $SYS_SEC.$SYS_NSEC"
fi
echo ""

# 4. PTP Port Status
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🔌 4. PTP Port Status"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

PORT_STATE=$(pmc -u -b 0 -d $INTERFACE 'GET PORT_DATA_SET' 2>/dev/null | grep "portState" | awk '{print $2}')
if [ "$PORT_STATE" == "SLAVE" ]; then
    echo -e "Port State:              ${GREEN}✓ $PORT_STATE${NC} (correct)"
else
    echo -e "Port State:              ${YELLOW}$PORT_STATE${NC}"
fi
echo ""

# 5. Offset Statistics
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "📊 5. Offset Statistics"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Get recent offset values from phc2sys logs
echo "Recent phc2sys offset values:"
journalctl -u phc2sys-client.service --no-pager --no-pager -n 20 | grep "offset" | tail -5 | \
    awk '{print "  " $0}'

echo ""

# Calculate from time status
TIME_STATUS=$(pmc -u -b 0 -d $INTERFACE 'GET TIME_STATUS_NP' 2>/dev/null | grep "master_offset")
if [ -n "$TIME_STATUS" ]; then
    echo "PTP master_offset:        $TIME_STATUS"
fi
echo ""

# 6. Hardware Capabilities
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🖥️  6. Hardware Timestamping Support"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# ethtool -T output format: supported features listed under capabilities
# Check if grep finds the matching line
HW_RX_CHECK=$(ethtool -T $INTERFACE 2>/dev/null | grep "hardware-receive")
HW_TX_CHECK=$(ethtool -T $INTERFACE 2>/dev/null | grep "hardware-transmit")

echo -n "hardware-receive:        "
if [ -n "$HW_RX_CHECK" ]; then
    echo -e "${GREEN}✓ Supported${NC}"
else
    echo -e "${RED}✗ Not Supported${NC}"
fi

echo -n "hardware-transmit:       "
if [ -n "$HW_TX_CHECK" ]; then
    echo -e "${GREEN}✓ Supported${NC}"
else
    echo -e "${RED}✗ Not Supported${NC}"
fi
echo ""

# 7. Summary
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "📝 7. Summary"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

ISSUES=0

# Check phc2sys
if ! systemctl is-active --quiet phc2sys-client.service; then
    echo -e "${RED}✗ phc2sys is not running${NC}"
    ISSUES=$((ISSUES + 1))
else
    echo -e "${GREEN}✓ phc2sys is running${NC}"
fi

# Check systemd-timesyncd
if systemctl is-active --quiet systemd-timesyncd.service; then
    echo -e "${YELLOW}⚠ systemd-timesyncd is running (may cause conflicts)${NC}"
    ISSUES=$((ISSUES + 1))
else
    echo -e "${GREEN}✓ systemd-timesyncd is stopped${NC}"
fi

# Check PTP port state
if [ "$PORT_STATE" == "SLAVE" ]; then
    echo -e "${GREEN}✓ PTP port is in SLAVE mode${NC}"
else
    echo -e "${RED}✗ PTP port is not in SLAVE mode${NC}"
    ISSUES=$((ISSUES + 1))
fi

echo ""

if [ $ISSUES -eq 0 ]; then
    echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${GREEN}✓ All checks passed! PTP sync is working correctly.${NC}"
    echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
else
    echo -e "${RED}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${RED}✗ Found $ISSUES issue(s). Please check above.${NC}"
    echo -e "${RED}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
fi

echo ""
echo "========================================"
echo "Useful Commands:"
echo "  sudo journalctl -u phc2sys-client -f     (monitor phc2sys logs)"
echo "  sudo phc2sys -s $INTERFACE -c CLOCK_REALTIME -w -u  (run in foreground)"
echo "========================================"
