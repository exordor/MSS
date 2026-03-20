# VNC Server Setup Guide for Ubuntu 22.04 (ARM64)

## Overview
This document describes how to set up TigerVNC server with XFCE desktop on Ubuntu 22.04 ARM64, including troubleshooting for systemd service integration.

## System Requirements
- OS: Ubuntu 22.04 (ARM64/Jetson)
- Desktop: XFCE4
- VNC: TigerVNC 1.12.0+

## Installation

### 1. Install Packages
```bash
sudo apt update
sudo apt install tigervnc-standalone-server xfce4 xfce4-goodies -y
```

### 2. Set VNC Password
```bash
vncpasswd
```

### 3. Configure xstartup
```bash
mkdir -p ~/.vnc
cat > ~/.vnc/xstartup << 'EOF'
#!/bin/bash
unset SESSION_MANAGER
unset DBUS_SESSION_BUS_ADDRESS
exec startxfce4
EOF
chmod +x ~/.vnc/xstartup
```

### 4. Install systemd Service
```bash
sudo cp vncserver@.service /etc/systemd/system/
sudo ./install_vnc_service.sh
```

## Connection Information
- Port: 5902
- Address: `<server-ip>:5902`
- Example: `192.168.0.200:5902`

## Common Commands

### Manual Control
```bash
# Start manually
vncserver -localhost no :2

# Stop manually
vncserver -kill :2

# List active sessions
vncserver -list
```

### Service Control
```bash
# Check status
sudo systemctl status vncserver@2.service

# Start service
sudo systemctl start vncserver@2.service

# Stop service
sudo systemctl stop vncserver@2.service

# Restart service
sudo systemctl restart vncserver@2.service

# View logs
sudo journalctl -u vncserver@2.service -f
```

## Troubleshooting

### Issue 1: Black Screen After Connection

**Symptoms:** VNC connects successfully but shows only a black screen.

**Cause:** Desktop environment fails to start due to incorrect xstartup configuration or missing desktop packages.

**Solution:**
1. Check VNC log: `tail -50 ~/.vnc/ubuntu:5902.log`
2. Verify xstartup content: `cat ~/.vnc/xstartup`
3. Ensure desktop is installed: `which startxfce4`
4. Use a working xstartup:
   ```bash
   cat > ~/.vnc/xstartup << 'EOF'
   #!/bin/bash
   unset SESSION_MANAGER
   unset DBUS_SESSION_BUS_ADDRESS
   exec startxfce4
   EOF
   chmod +x ~/.vnc/xstartup
   ```

### Issue 2: systemd Service Timeout

**Symptoms:** Service fails with "timeout exceeded" error, even though manual start works.

**Root Cause:** PID file path mismatch between systemd configuration and actual VNC behavior.

**Details:**
- VNC creates PID file as: `~/.vnc/ubuntu:5902.pid` (hostname:port format)
- Default systemd config uses: `~/.vnc/%H:%i.pid` → `ubuntu:2.pid`
- systemd cannot find the PID file → cannot detect when service is ready

**Solution:** Use correct PID file path in service file:
```ini
[Unit]
Description=TigerVNC Server for Display %i
After=network-online.target

[Service]
Type=forking
User=eagrumo
Group=eagrumo
WorkingDirectory=/home/eagrumo

# Critical: PID file format is hostname:590%i.pid
PIDFile=/home/eagrumo/.vnc/ubuntu:590%i.pid

ExecStartPre=/bin/sh -c 'vncserver -kill :%i 2>/dev/null || true'
ExecStartPre=/bin/rm -f /tmp/.X%i-lock
ExecStartPre=/bin/rm -f /tmp/.X11-unix/X%i
ExecStart=/usr/bin/vncserver -localhost no :%i
ExecStop=/usr/bin/vncserver -kill :%i

Restart=on-failure
RestartSec=5
TimeoutStartSec=300

[Install]
WantedBy=multi-user.target
```

### Issue 3: Service Start Fails with "Display Already Taken"

**Symptoms:** Error messages about `/tmp/.X2-lock` or `/tmp/.X11-unix/X2`

**Cause:** Stale lock files from previous crashed VNC session.

**Solution:**
```bash
# Clean up locks
rm -f /tmp/.X2-lock /tmp/.X11-unix/X2 ~/.vnc/*:2.*

# Then restart service
sudo systemctl restart vncserver@2.service
```

### Issue 4: VNC Connection Frequently Drops

**Symptoms:** Connection works initially but drops after some time.

**Possible Causes:**
1. Network instability
2. Power management killing connection
3. Heavy desktop load causing timeouts

**Solution:** Use lighter desktop (XFCE instead of GNOME) and check network stability:
```bash
# Test network
ping -c 100 <client-ip>

# Check VNC process stability
watch -n 2 'ps aux | grep Xtigervnc'
```

## Desktop Environment Comparison

| Desktop | Memory | Startup Time | Recommendation |
|---------|--------|--------------|----------------|
| LXDE    | ~200MB | Fast         | Good for VNC   |
| XFCE4   | ~400MB | Medium       | **Recommended** |
| GNOME   | ~800MB | Slow         | Not for VNC    |

## Security Notes

### Allow LAN Access Only
The service uses `-localhost no` to allow LAN connections. For public exposure, use SSH tunneling:

```bash
# On client machine, create SSH tunnel
ssh -L 5902:localhost:5902 user@server-ip

# Then connect to localhost:5902
```

### Firewall
If UFW is enabled, open VNC port:
```bash
sudo ufw allow 5902/tcp
```

## Files Reference

| File | Purpose |
|------|---------|
| `~/.vnc/xstartup` | Desktop session startup script |
| `~/.vnc/passwd` | VNC password file |
| `~/.vnc/ubuntu:5902.log` | VNC server log |
| `/etc/systemd/system/vncserver@.service` | systemd service template |
| `/etc/systemd/system/vncserver@2.service` | Display :2 service instance |
