#!/bin/bash

# PTP System Clock Sync Verification Script
# 验证 phc2sys 是否正确将 PTP 时间同步到系统时钟
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
echo ""

# Get PHC time
PHC_TIME=$(phc_ctl $INTERFACE get 2>/dev/null | grep "clock time" | awk '{print $4}' || echo "N/A")
if [ "$PHC_TIME" != "N/A" ]; then
    PHC_SEC=$(echo $PHC_TIME | cut -d'.' -f1)
    PHC_NSEC=$(echo $PHC_TIME | cut -d'.' -f2)
    PHC_DATE=$(date -d @$PHC_SEC +"%Y-%m-%d %H:%M:%S")
    echo "PHC Time (eno1):        $PHC_DATE.$PHC_NSEC"
else
    echo -e "${RED}PHC Time (eno1):        Cannot read${NC}"
fi

# Get System time
SYS_TIME=$(date +"%Y-%m-%d %H:%M:%S.%N")
echo "System Time:            $SYS_TIME"
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

# ethtool -T 输出格式: capabilities 下列出支持的特性
# 检查 grep 是否找到对应行
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
