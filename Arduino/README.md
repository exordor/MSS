# Thruster & Flow Meter Control (Arduino UNO R4 WiFi)

A dual thruster control system with integrated flow meter and DHT22 temperature/humidity sensors for Arduino UNO R4 WiFi, using dual-port UDP communication for low-latency real-time control.

## Features

- **Dual Thruster Control**: Two ESC outputs for differential thrust
- **RC Fallback**: Automatic switch to RC receiver when UDP timeout
- **Flow Meter**: Real-time flow rate and volume measurement
- **DHT22 Sensors**: Dual temperature and humidity monitoring (D12, D13)
- **Dual-Port UDP**: Data (8888) and heartbeat (8889) separated for reliability
- **PING Heartbeat (8889)**: Jetson keeps Arduino "online" without touching data port
- **Multi-Network WiFi**: Auto-connect to configured networks with reconnection
- **LED Matrix Status**: Onboard LED matrix blinks while WiFi is connecting and stays lit when connected
- **Hardware PWM ESC Output**: Uses UNO R4 `PwmOut`, so DHT reads do not distort ESC pulses

## Hardware

| Component | Pin | Description |
|-----------|-----|-------------|
| RC Right IN | D2 | PWM input from RC receiver |
| RC Left IN | D3 | PWM input from RC receiver |
| ESC Right OUT | D9 | Output to right ESC |
| ESC Left OUT | D10 | Output to left ESC |
| **Flow Sensor** | **D7** | **Flow meter signal (polling mode)** |
| **DHT22 #1** | **D12** | **Temperature/Humidity sensor #1** |
| **DHT22 #2** | **D13** | **Temperature/Humidity sensor #2** |
| **LED Matrix** | **Onboard** | **WiFi status indicator** |

## Specifications

| Parameter | Value |
|-----------|-------|
| Pipe diameter | 26 mm |
| Calibration factor (K) | 5 Hz per L/min |
| Pulses per liter | 300 |
| Flow update rate | 1 Hz |
| **DHT22 update rate** | **1 Hz (read every 2.5s)** |
| Status update rate | 10 Hz |
| Heartbeat interval | 1000 ms |
| UDP timeout | 2000 ms |
| **WiFi command rate limit** | **20 ms min interval (50 Hz max)** |
| **RC deadband** | **±40 µs (joystick drift resistance)** |
| **WiFi filter** | **100% alpha (direct control)** |
| **RC filter** | **25% alpha (smooth)** |
| **ESC neutral hold at boot** | **2000 ms** |
| **UDP socket start delay after WiFi link-up** | **300 ms** |

## Wiring

```
Flow Sensor Signal  →  D7
DHT22 #1 Data       →  D12
DHT22 #2 Data       →  D13
RC Receiver Right   →  D2
RC Receiver Left    →  D3
Right ESC           →  D9
Left ESC            →  D10
```

## UDP Communication (Dual Port)

### Architecture

The system uses two separate UDP ports for cleaner protocol separation:

| Port | Direction | Purpose |
|------|-----------|---------|
| **8888** | Bidirectional | Data (commands, status, flow) |
| **8889** | Bidirectional | Heartbeat (Jetson PING → Arduino, Arduino HEARTBEAT → clients) |

### Connection

- **Protocol**: UDP
- **Data Port**: 8888
- **Heartbeat Port**: 8889
- **Arduino IP**: 192.168.50.100 (configurable)
- **Heartbeat Broadcast**: 192.168.50.255:8889 (always when WiFi connected)
- **Jetson Unicast Heartbeat**: 192.168.50.200:28887 (only after PING)
- **Important**: Arduino does not start unicast `S/F/D` traffic until Jetson first sends `PING` or a `C ...` command

### Message Protocol

#### Data Port (8888)

| Direction | Format | Purpose | Rate Limit |
|-----------|--------|---------|-------------|
| Client → Arduino | `C <left_us> <right_us>\n` | Thruster command | **20ms min** |
| Arduino → Client | `S <mode> <left_us> <right_us>\n` | Thruster status (to 28888, 28889) | 10 Hz |
| Arduino → Client | `F <freq_hz> <flow_lmin> <velocity_ms> <total_liters>\n` | Flow data (to 28888, 28889) | 5 Hz |
| Arduino → Client | `D <temp1> <hum1> <temp2> <hum2>\n` | DHT data (to 28888, 28889) | 1 Hz |

> **Note**: All data messages (S, F, D) are sent to both port 28888 (Jetson data) and 28889 (Monitor).

#### Heartbeat Port (8889)

| Direction | Format | Purpose | Rate |
|-----------|--------|---------|------|
| Jetson → Arduino | `PING\n` | Online/keep-alive | 1 Hz |
| Arduino → Client | `HEARTBEAT\n` | Keep-alive (broadcast + optional unicast) | 1 Hz |

### Protocol Examples

```
# Command (Client → Arduino, port 8888)
C 1600 1600\n

# Heartbeat ping (Jetson → Arduino, port 8889)
PING\n

# Status response (Arduino → Client, port 8888)
S 1 1600 1600\n

# Flow data (Arduino → Client, port 8888)
F 25.50 5.10 0.1601 12.345\n

# DHT data (Arduino → Client, port 28888 and 28889)
D 25.30 65.00 24.80 68.50\n

# Heartbeat (Arduino → Broadcast/Client, port 8889)
HEARTBEAT\n
```

### Message Fields

| Field | Type | Range | Description |
|-------|------|-------|-------------|
| `C` command | `<left_us>` | 1100-1900 | Left ESC pulse width in µs |
| | `<right_us>` | 1100-1900 | Right ESC pulse width in µs |
| `S` status | `<mode>` | 0=RC, 1=WiFi | Current control mode |
| | `<left_us>` | 1100-1900 | Current left output |
| | `<right_us>` | 1100-1900 | Current right output |
| `F` flow | `<freq_hz>` | float | Flow frequency in Hz |
| | `<flow_lmin>` | float | Flow rate in L/min |
| | `<velocity_ms>` | float | Velocity in m/s |
| | `<total_liters>` | float | Accumulated volume in L |
| `D` dht | `<temp1>` | float | Temperature from sensor #1 (°C, D12) |
| | `<hum1>` | float | Humidity from sensor #1 (%, D12) |
| | `<temp2>` | float | Temperature from sensor #2 (°C, D13) |
| | `<hum2>` | float | Humidity from sensor #2 (%, D13) |

## Connection Detection & Handshake

### Dual-Port Heartbeat System

```
Client startup:
1. Bind to local port for data (ephemeral) → Arduino:8888
2. Bind to local port 8889 for heartbeat (rx + tx)
3. Receive Arduino HEARTBEAT on 8889 (broadcast, every 1s)
4. Send PING to Arduino:8889 (keep-alive)
5. Arduino starts unicast HEARTBEAT (28887) + STATUS/FLOW (28888) after PING

Continuous operation:
- Send PING every 1s (keep-alive on 8889)
- Receive broadcast HEARTBEAT on 8889
- If 2s without PING at Arduino → Arduino switches to RC and stops unicast data
```

### Current Implementation Notes

- ESC outputs are held at neutral for 2 seconds on boot before WiFi connection starts.
- The LED matrix blinks while WiFi is connecting or reconnecting, and stays lit when WiFi is connected.
- UDP sockets are started only after WiFi is up and the link has been stable for about 300 ms.
- Broadcast `HEARTBEAT` packets can appear as soon as WiFi is up, but unicast `S/F/D` packets are sent only after Jetson is marked online by `PING` or `C ...`.
- The current UNO R4 `WiFiS3` core uses a blocking `WiFi.begin()` internally, so each failed SSID can still stall boot or reconnect for roughly 10 seconds before the next network is tried.

### Why Separate Ports?

1. **Protocol Clarity**: Heartbeat traffic separated from data
2. **No Interference**: PING doesn't affect command rate limiting
3. **Easy Filtering**: Can filter heartbeat traffic separately if needed
4. **Independent Channels**: Different QoS can be applied per port

## Control Characteristics

### RC vs WiFi Filtering

The system uses different filtering parameters for optimal performance with each input type:

| Characteristic | RC (Joystick) | WiFi (UDP) |
|----------------|---------------|-----------|
| Filter Alpha | 25% (smooth) | 100% (direct) |
| Max Step | 15µs/cycle | 500µs/cycle |
| Deadband | ±40µs | N/A |
| Purpose | Resist drift | Low latency |

**Why Different?**
- **RC inputs** have physical joystick drift, hand tremors, and signal noise → needs strong smoothing
- **WiFi inputs** are precise digital values with no drift → can use fast, responsive filtering

### Performance

| Metric | RC | WiFi |
|--------|-------|------|
| Response Time | ~200-300ms (smooth ramp) | ~40-80ms (fast) |
| Max Command Rate | Limited by human | 50 Hz (20ms min) |
| Drift Resistance | High (±40µs deadband) | N/A (digital) |
| Precision | Medium (joystick dependent) | High (exact values) |

## Control Priority

1. **WiFi/UDP commands** (if receiving data)
2. **RC receiver** (if UDP timeout)
3. **Neutral failsafe** (if both unavailable)

## RC Control Mode

The system supports a 9-gear mode for discrete speed control:

| Gear | Pulse Width | Description |
|------|-------------|-------------|
| 1 | 1100 µs | Reverse max |
| 2 | 1200 µs | Reverse high |
| 3 | 1300 µs | Reverse mid |
| 4 | 1400 µs | Reverse low |
| 5 | 1500 µs | Neutral stop |
| 6 | 1600 µs | Forward low |
| 7 | 1700 µs | Forward mid |
| 8 | 1800 µs | Forward high |
| 9 | 1900 µs | Forward max |

To switch to continuous mode, set `ENABLE_GEAR_MODE = false` in the code.

## WiFi Configuration

The Arduino automatically tries to connect to configured networks in order:

1. IGE-Geomatics-sense-mobile (static IP: 192.168.50.100)
2. GL-MT1300-a42 (static IP: 192.168.50.100)
3. ISSE_2.4 (static IP: 192.168.50.100)

Edit the `wifiNetworks[]` array in the code to add your networks.

### Static IP Notes

- Static IP is configured with the `WiFiS3` signature `config(local_ip, dns_server, gateway, subnet)`.
- The bundled profiles reuse the router IP as both DNS server and gateway.
- If Jetson is not fixed at `192.168.50.200`, update `JETSON_IP` in the sketch or communication will fail even if WiFi is connected.

## Serial Output

Connect via USB at 115200 baud for debugging:

```
=== WiFi UDP + RC Thruster Control + Flow Meter + DHT22 ===
RC Control Mode: Gear Mode (9 gears, 100µs intervals)

RC input pins configured
RC interrupts attached
Flow meter sensor configured on D7
LED Matrix WiFi indicator initialized
DHT22 sensors configured on D12 and D13
ESCs initialized to neutral (1500 us), holding for 2000 ms
WiFi background connect enabled - RC available immediately

=== WiFi Background Connect ===
WiFi connect attempt [1/3]: IGE-Geomatics-sense-mobile
  Using static IP: 192.168.50.100

WiFi connected
  Network: IGE-Geomatics-sense-mobile
  IP Address: 192.168.50.100
  Gateway: 192.168.50.1
  Subnet: 255.255.255.0
  RSSI: -45 dBm

Data UDP server started on port 8888
Heartbeat server started on port 8889
Ready for UDP control commands

=== System Ready ===
Control Priority: UDP > RC > Failsafe
Flow Meter: D7 polling mode, 1 Hz update rate
DHT22: D12 and D13, 1 Hz update rate
UDP: Listen 8888, Send S/F/D to 192.168.50.200:28888
     S/F/D also sent to 192.168.50.200:28889 (monitor)
     HEARTBEAT broadcast to 192.168.50.255:8889
     HEARTBEAT unicast to 192.168.50.200:28887 (Jetson)
```

## Python Client Example

### Basic Client (Dual Port)

```python
import socket
import select

ARDUINO_IP = "192.168.50.100"
DATA_PORT = 8888
HEARTBEAT_PORT = 8889

# Create two sockets
data_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
data_sock.bind(('', 0))  # Any available port

heartbeat_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
heartbeat_sock.bind(('', HEARTBEAT_PORT))

print(f"Data socket: {data_sock.getsockname()[1]} -> {ARDUINO_IP}:{DATA_PORT}")
print(f"Heartbeat socket: {HEARTBEAT_PORT} <- broadcast/{ARDUINO_IP}:{HEARTBEAT_PORT}")

# Send keep-alive PING to heartbeat port
heartbeat_sock.sendto(b"PING\n", (ARDUINO_IP, HEARTBEAT_PORT))

# Listen for responses
while True:
    sockets = [data_sock, heartbeat_sock]
    readable, _, _ = select.select(sockets, [], [], 0.1)

    for sock in readable:
        data, addr = sock.recvfrom(256)
        msg = data.decode('utf-8').strip()

        if sock == heartbeat_sock:
            print(f"[HEARTBEAT] {msg}")
        elif msg.startswith('S '):
            print(f"[STATUS] {msg}")
        elif msg.startswith('F '):
            print(f"[FLOW] {msg}")
        elif msg.startswith('D '):
            print(f"[DHT] {msg}")
```

### Using the Test Script

A comprehensive test script is included:

```bash
# Monitor mode (listen only)
python3 udp_test.py --mode monitor --heartbeat-port 8889

# Monitor with keep-alive (send PING every second)
python3 udp_test.py --mode monitor --keep-alive --heartbeat-port 8889

# Interactive mode (send commands)
python3 udp_test.py --mode interactive --heartbeat-port 8889

# 10Hz latency test (measure control delay)
python3 udp_test.py --mode hz10 --duration 10 --heartbeat-port 8889

# Thruster control test
python3 udp_test.py --mode thruster --heartbeat-port 8889

# Heartbeat test (test for 30 seconds)
python3 udp_test.py --mode heartbeat --duration 30 --heartbeat-port 8889

# Custom ports
python3 udp_test.py --data-port 8888 --heartbeat-port 8889

# Custom IP
python3 udp_test.py --ip 192.168.50.100
```

### Interactive Commands

| Command | Action |
|---------|--------|
| `n` / `neutral` | Send neutral (1500, 1500) |
| `f` / `forward` | Send forward (1600, 1600) |
| `b` / `backward` | Send backward (1400, 1400) |
| `l` / `left` | Turn left (1500, 1600) |
| `r` / `right` | Turn right (1600, 1500) |
| `ping` | Send PING (handshake) |
| `1550 1600` | Custom command |
| `stats` | Show statistics |
| `q` / `quit` | Exit |

## Jetson/ROS Integration

### Key Implementation Points

1. **Dual Socket Setup**: Create two UDP sockets, one for data (port 8888) and one for heartbeat (port 8889)
2. **Initial Handshake**: Send `PING` immediately after connection on port 8889
3. **Keep-Alive**: Send `PING` every 1 second on port 8889 to maintain connection
4. **Use `select()`**: Monitor both sockets simultaneously for incoming data
5. **Handle Rate Limiting**: WiFi commands have 20ms minimum interval, PING does not

### C++ ROS Node Structure

```cpp
// Thread 1: UDP receive (both ports)
void udpReceiveThread() {
    while (running) {
        // Use select() to monitor both sockets
        // Process messages based on source port
    }
}

// Thread 2: Keep-alive
void keepAliveThread() {
    while (running) {
        send_ping(heartbeat_sock);
        sleep(1);
    }
}

// Main: ROS publishers/subscribers
// Publish: /thruster_status, /flow_data
// Subscribe: /cmd_thruster
```

## Calibration

### Flow Meter

Modify these constants if needed:

```cpp
const float K_HZ_PER_LMIN = 5.0f;       // f = 5*Q (frequency per flow rate)
const float PULSES_PER_L = 300.0f;      // 1L ≈ 300 pulses
const float DIAMETER_M = 0.026f;        // 26 mm pipe diameter
```

### Control Response Tuning

The following constants can be adjusted to change control behavior:

```cpp
// WiFi (Low Latency)
const int WIFI_FILTER_ALPHA = 100;    // 100% = no filtering, direct control
const int WIFI_MAX_STEP_US = 500;     // Higher = faster ramp (10-500µs)
const unsigned long MIN_CMD_INTERVAL_MS = 20;  // Min time between commands

// RC (Smooth, Drift-Resistant)
const int RC_FILTER_ALPHA = 25;       // Lower = smoother (10-50%)
const int RC_MAX_STEP_US = 15;        // Lower = slower ramp (5-50µs)
const int DEADBAND_US = 40;            // Deadband around center (20-100µs)
```

**Tuning Guide:**
- Increase `WIFI_FILTER_ALPHA` for smoother WiFi control (less jitter)
- Increase `WIFI_MAX_STEP_US` for faster WiFi changes
- Decrease `RC_FILTER_ALPHA` for faster RC response
- Increase `DEADBAND_US` if joystick causes unintended movement

## Troubleshooting

### "Jetson: OFFLINE" in Serial Monitor

- Check client is sending data to port 8888
- Verify heartbeat is being received on port 8889
- Send PING to port 8889 to mark Jetson online
- Verify IP address configuration matches

### No status/flow after PING

- Ensure Jetson is sending PING to port 8889
- Check data port (8888) is correct
- Verify firewall is not blocking UDP

### WiFi connected but no `S/F/D` data

- Confirm Jetson sends `PING\n` to port 8889 immediately after link-up
- `HEARTBEAT` broadcast alone does not mark Jetson online on the Arduino side
- Check Jetson IP really is `192.168.50.200` or update `JETSON_IP` in the sketch
- Wait for `Data UDP server started on port 8888` in Serial before expecting traffic

### No heartbeat on port 8889

- Verify heartbeat port (8889) is correct
- Check client is bound to port 8889
- Confirm broadcast traffic is allowed on the WiFi network

### Slow startup / delayed reconnect

- The current UNO R4 `WiFiS3` core blocks inside `WiFi.begin()` during each connection attempt
- A failed SSID can therefore delay boot or reconnect by roughly 10 seconds before the next network is tried
- This is a current implementation limitation, not just a serial logging delay

### Command rate limiting

- WiFi commands have **20ms minimum interval** (max 50 Hz)
- PING is NOT rate limited (can be sent anytime)
- Use keep-alive mode to maintain connection
- RC control has **separate filtering** (25% alpha, smooth) to resist joystick drift

### No flow data

- Verify flow sensor connected to D7
- Check sensor power supply
- Increase `FLOW_UPDATE_INTERVAL_MS` for testing

### RC control not working

- Verify RC receiver connected to D2 and D3
- Check RC receiver is bound (TX light on)
- Verify PWM output range (1000-2000µs)

### No DHT data

- Verify DHT22 sensors connected to D12 and D13
- Check sensor power supply (3.3V or 5V)
- Add 10kΩ pull-up resistor between DATA and VCC if not built into module
- DHT22 requires 2+ seconds between reads (reading too fast returns NaN)
- Check DHT library is installed in Arduino IDE

## License

MIT License
