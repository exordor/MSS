#include <WiFiS3.h>
#include <Servo.h>
#include <WiFiUdp.h>
#include "DHT.h"

/*
 * Dual Thrusters Control + Flow Meter + DHT22 - WiFi UDP + RC Hybrid Mode
 *
 * Control Priority:
 *   1. WiFi/UDP commands (if receiving data)
 *   2. RC receiver (if UDP timeout)
 *   3. Neutral failsafe (if both unavailable)
 *
 * Communication (UDP):
 *   - Arduino Listen: Port 8888 (C commands)
 *   - Arduino Listen: Port 8889 (PING heartbeat from Jetson)
 *   - Arduino Send to: 192.168.50.200:28888 (S status, F flow, D dht)
 *   - Arduino Send to: 192.168.50.200:28887 (HEARTBEAT to Jetson, when online)
 *   - Arduino Send to: 192.168.50.200:28889 (D dht, HEARTBEAT to Monitor, when online) [optional]
 *   - Arduino Broadcast: 192.168.50.255:8889 (HEARTBEAT broadcast when WiFi connected)
 *   - Command format: C <left_us> <right_us>\n
 *   - Ping format: PING\n (Jetson heartbeat to Arduino on 8889)
 *   - Status format: S <mode> <left_us> <right_us>\n
 *   - Flow data format: F <freq_hz> <flow_lmin> <velocity_ms> <total_liters>\n
 *   - DHT data format: D <temp1> <hum1> <temp2> <hum2>\n (D12, D13) - sent to 28888 and 28889
 *   - Heartbeat: Arduino sends "HEARTBEAT\n" every 1s to both ports
 *   - Mode: 0=RC, 1=WiFi
 *
 * Jetson Programs:
 *   - Control node: Sends C commands on 8888, sends PING on 8889,
 *                   receives S/F/D on 28888, HEARTBEAT on 28887
 *   - Monitor node: Receives D on 28889, HEARTBEAT on 28889 (optional)
 *   - Connection detected by timeout: 2s without data = offline
 */

// === WiFi Configuration ===

// WiFi network list - add all available networks here
const int MAX_WIFI_NETWORKS = 5;

struct WifiNetwork {
  const char* ssid;
  const char* password;
  IPAddress local_ip;
  IPAddress gateway;
  IPAddress subnet;
  bool use_dhcp;  // true = use DHCP, false = use static IP
};

WifiNetwork wifiNetworks[MAX_WIFI_NETWORKS] = {
    // Network 1: IGE (static IP)
  {
    .ssid = "IGE-Geomatics-sense-mobile",
    .password = "kmhxTFWNQKH-BCiBz9Co",
    .local_ip = IPAddress(192, 168, 50, 100),
    .gateway = IPAddress(192, 168, 50, 1),
    .subnet = IPAddress(255, 255, 255, 0),
    .use_dhcp = false
  },
  {
    .ssid = "GL-MT1300-a42",
    .password = "goodlife",
    .local_ip = IPAddress(192, 168, 50, 100),
    .gateway = IPAddress(192, 168, 50, 1),
    .subnet = IPAddress(255, 255, 255, 0),
    .use_dhcp = false
  },
  // Network 3: ISSE (static IP)
  {
    .ssid = "ISSE_2.4",
    .password = "TheAnswerIs42",
    .local_ip = IPAddress(192, 168, 50, 100),
    .gateway = IPAddress(192, 168, 50, 1),
    .subnet = IPAddress(255, 255, 255, 0),
    .use_dhcp = false
  },
  // Network 4: Add more networks as needed (max 5)
};

// Track which network is currently connected
int currentNetworkIndex = -1;

// WiFi auto-reconnect configuration
const unsigned long WIFI_CHECK_INTERVAL_MS = 2000;  // Check WiFi every 2 seconds
const unsigned long WIFI_RECONNECT_DELAY_MS = 5000; // Wait 5s before reconnect attempt
const int MAX_RECONNECT_ATTEMPTS = 3;               // Max reconnect attempts per network
unsigned long lastWifiCheckMs = 0;
unsigned long lastWifiDisconnectMs = 0;
int reconnectAttemptCount = 0;
bool reconnectInProgress = false;

// UDP Configuration
const unsigned int UDP_PORT = 8888;         // Data port (commands, status, flow)
const unsigned int HEARTBEAT_PORT = 8889;   // Heartbeat port (PING in, broadcast out)
WiFiUDP udp;              // Data UDP
WiFiUDP udpHeartbeat;     // Heartbeat UDP
#define UDP_BUFFER_SIZE 128
char udpBuffer[UDP_BUFFER_SIZE];

// === Jetson Configuration (fixed IP and port) ===
// Arduino sends heartbeat and data to this address
const IPAddress JETSON_IP(192, 168, 50, 200);  // Jetson IP address
const uint16_t JETSON_PORT = 28888;              // Jetson data port
const uint16_t JETSON_HEARTBEAT_PORT = 28887;    // Jetson heartbeat port
const uint16_t MONITOR_HEARTBEAT_PORT = 28889;   // Monitor heartbeat port
const IPAddress HEARTBEAT_BROADCAST_IP(192, 168, 50, 255); // Subnet broadcast
const bool ENABLE_HEARTBEAT_BROADCAST = true;

// === Pin Configuration ===
const int CH_RIGHT_IN = 2;     // RC Right channel PWM input (Pin 2)
const int CH_LEFT_IN = 3;      // RC Left channel PWM input (Pin 3)
const int ESC_RIGHT_OUT = 9;   // Right ESC signal output
const int ESC_LEFT_OUT = 10;   // Left ESC signal output

// === Flow Meter Configuration ===
const byte FLOW_SENSOR_PIN = 7;           // D7 for flow sensor
const float K_HZ_PER_LMIN = 5.0f;         // f = 5*Q (frequency per flow rate)
const float PULSES_PER_L = 300.0f;        // 1L ≈ 300 pulses
const float DIAMETER_M = 0.026f;          // 26 mm pipe diameter
const float PIPE_AREA = 3.1415926f * (DIAMETER_M * 0.5f) * (DIAMETER_M * 0.5f);
const unsigned long FLOW_CALC_INTERVAL_MS = 1000;    // Flow calculation window (1s for accurate pulse counting)
const unsigned long FLOW_SEND_INTERVAL_MS = 200;      // Flow UDP send rate (5 Hz)

// === DHT22 Configuration ===
const byte DHT_PIN_1 = 12;                             // D12 for DHT22 #1 data
const byte DHT_PIN_2 = 13;                             // D13 for DHT22 #2 data
#define DHT_TYPE DHT22
const unsigned long DHT_READ_INTERVAL_MS = 2500;       // DHT22 max 0.5 Hz
const unsigned long DHT_SEND_INTERVAL_MS = 1000;       // 1 Hz UDP send rate

// === Timing Constants ===
const unsigned long RC_FAILSAFE_MS = 200;            // RC signal timeout
const unsigned long UDP_TIMEOUT_MS = 2000;           // UDP timeout (2s without data = offline)
const unsigned long JETSON_ONLINE_TIMEOUT_MS = 2000; // Jetson online if ping/command seen recently
const unsigned long HEARTBEAT_INTERVAL_MS = 1000;    // Heartbeat send interval (1 second, broadcast mode)
const unsigned long WIFI_GRACE_MS = 400;             // Hold-last grace after timeout
const int DECAY_STEP_US = 5;                         // Soft decay step toward 1500
const unsigned long STATUS_SEND_INTERVAL_MS = 100;   // Status update rate (10Hz)

// === ESC Configuration ===
const int RX_VALID_MIN = 950;
const int RX_VALID_MAX = 2000;
const int ESC_MIN = 1100;
const int ESC_MID = 1500;
const int ESC_MAX = 1900;
const int DEADBAND_US = 40;  // Increased deadband to resist joystick drift (±40µs around center)

// === Servo Objects ===
Servo escL, escR;

// === RC State Variables ===
// RC state - interrupt-based capture
volatile unsigned long rRiseMicros = 0, rPulseMicros = 0;
volatile unsigned long lRiseMicros = 0, lPulseMicros = 0;
unsigned long lastRcUpdateL = 0;
unsigned long lastRcUpdateR = 0;

// RC filtering and smoothing (separate from WiFi for different response characteristics)
int rcAvgL = ESC_MID;
int rcAvgR = ESC_MID;
const int RC_FILTER_ALPHA = 25;       // RC filter (25% = smooth, resists joystick drift)
const int RC_MAX_STEP_US = 15;        // RC ramp limiting (15µs per cycle = smooth RC control)

const int WIFI_FILTER_ALPHA = 100;    // WiFi filter (100% = no filtering, direct control)
const int WIFI_MAX_STEP_US = 500;     // WiFi ramp limiting (500µs per cycle = aggressive WiFi control for high speeds)

// === PWM Gear Mode Settings ===
const bool ENABLE_GEAR_MODE = true;  // Enable gear mode (false=continuous)
const int NUM_GEARS = 9;             // Number of gears (including neutral)

// Gear definitions: 9-gear mode (4 reverse | neutral | 4 forward) - 100µs intervals
const int GEAR_VALUES[NUM_GEARS] = {
  1100,  // Gear 1: Reverse max (-400µs)
  1200,  // Gear 2: Reverse high (-300µs)
  1300,  // Gear 3: Reverse mid (-200µs)
  1400,  // Gear 4: Reverse low (-100µs)
  1500,  // Gear 5: Neutral stop (0µs)
  1600,  // Gear 6: Forward low (+100µs)
  1700,  // Gear 7: Forward mid (+200µs)
  1800,  // Gear 8: Forward high (+300µs)
  1900   // Gear 9: Forward max (+400µs)
};

// Gear switching thresholds (based on actual RC output range)
// Assuming range ~1000-2000µs, each gear ~111µs
const int GEAR_THRESHOLDS[NUM_GEARS - 1] = {
  1056,  // < 1056: gear 1 (1000 + 56)
  1167,  // 1056-1167: gear 2 (+111)
  1278,  // 1167-1278: gear 3 (+111)
  1389,  // 1278-1389: gear 4 (+111)
  1500,  // 1389-1500: gear 5 neutral (+111)
  1611,  // 1500-1611: gear 6 (+111)
  1722,  // 1611-1722: gear 7 (+111)
  1833   // 1722-1833: gear 8 (+111), > 1833: gear 9
};

int rcOutL = ESC_MID;
int rcOutR = ESC_MID;

// === UDP/WiFi State ===
unsigned long lastWifiCmdMs = 0;
unsigned long lastUdpReceiveMs = 0;    // Last time any UDP data received
unsigned long lastJetsonPingMs = 0;    // Last time Jetson ping/command received
unsigned long lastHeartbeatMs = 0;     // Last heartbeat sent
int wifiOutL = ESC_MID;
int wifiOutR = ESC_MID;
bool haveWifiCmd = false;

// WiFi command buffer
#define CMD_BUFFER_SIZE 64
static char cmdBuffer[CMD_BUFFER_SIZE];
static int cmdBufferIndex = 0;

// WiFi command rate limiting (prevent excessive commands from overheating motors/ESCs)
const unsigned long MIN_CMD_INTERVAL_MS = 20;  // Minimum 20ms between commands (max 50 commands/sec) - LOW LATENCY
unsigned long lastWifiCommandSentMs = 0;

// WiFi filtering and smoothing
int wifiAvgL = ESC_MID;
int wifiAvgR = ESC_MID;

// === Current Output ===
int currentLeftUs = ESC_MID;
int currentRightUs = ESC_MID;
int currentMode = 0;  // 0=RC, 1=WiFi

// Status sending
unsigned long lastStatusSendMs = 0;

// === Flow Meter State ===
unsigned long lastFlowCalcMs = 0;     // Last time flow data was calculated
unsigned long lastFlowSendMs = 0;     // Last time flow data was sent via UDP
int lastFlowState = 0;
unsigned long flowChangeCount = 0;
float flowFreqHz = 0.0f;
float flowLmin = 0.0f;
float flowVelocity = 0.0f;
double totalLiters = 0.0;

// === DHT22 State ===
DHT dht1(DHT_PIN_1, DHT_TYPE);
DHT dht2(DHT_PIN_2, DHT_TYPE);
float dht1Temperature = 0.0f;    // Celsius (sensor 1, D12)
float dht1Humidity = 0.0f;       // Percentage (sensor 1, D12)
float dht2Temperature = 0.0f;    // Celsius (sensor 2, D13)
float dht2Humidity = 0.0f;       // Percentage (sensor 2, D13)
unsigned long lastDhtReadMs = 0;
unsigned long lastDhtSendMs = 0;

// === Helper Functions ===

inline bool isJetsonOnline(unsigned long now) {
  return (lastJetsonPingMs > 0) && (now - lastJetsonPingMs < JETSON_ONLINE_TIMEOUT_MS);
}

// Right channel interrupt handler
void onRightChange() {
  int level = digitalRead(CH_RIGHT_IN);
  unsigned long now = micros();
  if (level == HIGH) {
    rRiseMicros = now;
  } else {
    unsigned long width = now - rRiseMicros;
    // Only accept valid pulse widths (800-2200µs)
    if (width >= 800 && width <= 2200) {
      rPulseMicros = width;
    }
  }
}

// Left channel interrupt handler
void onLeftChange() {
  int level = digitalRead(CH_LEFT_IN);
  unsigned long now = micros();
  if (level == HIGH) {
    lRiseMicros = now;
  } else {
    unsigned long width = now - lRiseMicros;
    if (width >= 800 && width <= 2200) {
      lPulseMicros = width;
    }
  }
}

// Map input signal to gear position
int mapToGear(unsigned long inUs) {
  if (inUs == 0) return ESC_MID; // Timeout/no pulse
  if ((int)inUs < RX_VALID_MIN || (int)inUs > RX_VALID_MAX) return ESC_MID; // Invalid range
  if (abs((int)inUs - 1500) <= DEADBAND_US) return ESC_MID; // Center deadband

  // Select gear based on input value (9 gears)
  for (int i = 0; i < NUM_GEARS - 1; i++) {
    if (inUs < GEAR_THRESHOLDS[i]) {
      return GEAR_VALUES[i];
    }
  }
  return GEAR_VALUES[NUM_GEARS - 1];  // Highest gear
}

int mapLinearToEsc(long pulseUs) {
  if (pulseUs == 0) return ESC_MID; // Timeout/no pulse

  // Out of valid range -> neutral
  if (pulseUs < RX_VALID_MIN || pulseUs > RX_VALID_MAX) {
    return ESC_MID;
  }

  // Center deadband
  if (abs((int)pulseUs - 1500) <= DEADBAND_US) {
    return ESC_MID;
  }

  // Map RX range to ESC range
  long mapped = map(pulseUs, RX_VALID_MIN, RX_VALID_MAX, ESC_MIN, ESC_MAX);
  mapped = constrain(mapped, ESC_MIN, ESC_MAX);

  return (int)mapped;
}

// Unified mapping function: select continuous or gear mode based on setting
int mapToEsc(unsigned long inUs) {
  if (ENABLE_GEAR_MODE) {
    return mapToGear(inUs);
  } else {
    return mapLinearToEsc(inUs);
  }
}

void readRcInputs() {
  unsigned long now = millis();

  // Read pulse widths from interrupt capture (non-blocking)
  noInterrupts();
  unsigned long inR = rPulseMicros;
  unsigned long inL = lPulseMicros;
  interrupts();

  // Update timestamp if valid
  if (inR >= RX_VALID_MIN && inR <= RX_VALID_MAX) lastRcUpdateR = now;
  if (inL >= RX_VALID_MIN && inL <= RX_VALID_MAX) lastRcUpdateL = now;

  // Map to ESC range (using gear or linear mode)
  int outR = mapToEsc((long)inR);
  int outL = mapToEsc((long)inL);

  // Apply low-pass filter (RC uses smoother filtering to resist joystick drift)
  int filtR = (rcAvgR * (100 - RC_FILTER_ALPHA) + outR * RC_FILTER_ALPHA) / 100;
  int filtL = (rcAvgL * (100 - RC_FILTER_ALPHA) + outL * RC_FILTER_ALPHA) / 100;

  // Apply soft-start ramp limiting (RC uses slower ramp for smooth control)
  int deltaR = filtR - rcAvgR;
  if (deltaR > RC_MAX_STEP_US) deltaR = RC_MAX_STEP_US;
  if (deltaR < -RC_MAX_STEP_US) deltaR = -RC_MAX_STEP_US;
  rcAvgR += deltaR;

  int deltaL = filtL - rcAvgL;
  if (deltaL > RC_MAX_STEP_US) deltaL = RC_MAX_STEP_US;
  if (deltaL < -RC_MAX_STEP_US) deltaL = -RC_MAX_STEP_US;
  rcAvgL += deltaL;

  // Apply RC failsafe
  if (now - lastRcUpdateR > RC_FAILSAFE_MS) rcAvgR = ESC_MID;
  if (now - lastRcUpdateL > RC_FAILSAFE_MS) rcAvgL = ESC_MID;

  rcOutR = rcAvgR;
  rcOutL = rcAvgL;
}

// === Flow Meter Functions ===

// Lightweight pulse capture - call frequently throughout loop
// This ensures we don't miss pulses even during time-consuming operations
inline void pollFlowSensor() {
  // Single read for maximum speed
  int s = digitalRead(FLOW_SENSOR_PIN);
  if (s != lastFlowState) {
    flowChangeCount++;
    lastFlowState = s;
  }
}

// Update flow meter by polling D7 for state changes
void updateFlowMeter() {
  unsigned long now = millis();

  // Multiple samples for better capture rate
  for (int i = 0; i < 5; i++) {
    pollFlowSensor();
    delayMicroseconds(10);  // 10us delay between reads (total ~50us)
  }

  // Calculate flow rate at specified interval (1s window for accurate pulse counting)
  calculateFlowData(now);
}

// Separate calculation function (called by updateFlowMeter)
void calculateFlowData(unsigned long now) {
  if (now - lastFlowCalcMs >= FLOW_CALC_INTERVAL_MS) {
    unsigned long dtMs = now - lastFlowCalcMs;
    float dtS = dtMs / 1000.0f;

    unsigned long changes = flowChangeCount;
    flowChangeCount = 0;

    // Each pulse produces 2 changes (HIGH->LOW->HIGH)
    // Frequency = (changes / 2) / seconds
    float freqHz = (dtS > 0) ? ((changes / 2.0f) / dtS) : 0.0f;
    flowFreqHz = freqHz;

    // Flow rate: Q(L/min) = f(Hz) / 5
    float flowLmin = freqHz / K_HZ_PER_LMIN;
    flowLmin = flowLmin;

    // Velocity calculation
    float flow_m3s = (flowLmin * 0.001f) / 60.0f;
    float velocity = (PIPE_AREA > 0) ? (flow_m3s / PIPE_AREA) : 0.0f;
    flowVelocity = velocity;

    // Total volume: each pulse represents 1/300 of a liter
    double pulsesThisWindow = (double)changes / 2.0;
    totalLiters += pulsesThisWindow / PULSES_PER_L;

    lastFlowCalcMs = now;
  }
}

// === DHT22 Functions ===

void readDhtSensor(unsigned long now) {
  if (now - lastDhtReadMs < DHT_READ_INTERVAL_MS) {
    return;
  }
  lastDhtReadMs = now;

  // Read sensor 1 (D12)
  float h1 = dht1.readHumidity();
  float t1 = dht1.readTemperature();
  if (!isnan(h1) && !isnan(t1)) {
    dht1Humidity = h1;
    dht1Temperature = t1;
  }

  // Read sensor 2 (D13)
  float h2 = dht2.readHumidity();
  float t2 = dht2.readTemperature();
  if (!isnan(h2) && !isnan(t2)) {
    dht2Humidity = h2;
    dht2Temperature = t2;
  }
}

// === UDP Functions ===

// Send heartbeat to Jetson (fixed address, unicast)
void sendHeartbeat() {
  unsigned long now = millis();
  if (now - lastHeartbeatMs < HEARTBEAT_INTERVAL_MS) {
    return;
  }

  // Only send if WiFi is connected (non-blocking check)
  if (WiFi.status() != WL_CONNECTED) {
    return;
  }
  lastHeartbeatMs = now;

  // Broadcast heartbeat so Jetson can detect Arduino without sending first
  if (ENABLE_HEARTBEAT_BROADCAST) {
    udpHeartbeat.beginPacket(HEARTBEAT_BROADCAST_IP, HEARTBEAT_PORT);
    udpHeartbeat.print("HEARTBEAT\n");
    udpHeartbeat.endPacket();
  }

  // Send unicast heartbeats only when Jetson is online to avoid blocking
  if (isJetsonOnline(now)) {
    udpHeartbeat.beginPacket(JETSON_IP, JETSON_HEARTBEAT_PORT);
    udpHeartbeat.print("HEARTBEAT\n");
    udpHeartbeat.endPacket();

    // Optional: Monitor heartbeat (disabled)
    // udpHeartbeat.beginPacket(JETSON_IP, MONITOR_HEARTBEAT_PORT);
    // udpHeartbeat.print("HEARTBEAT\n");
    // udpHeartbeat.endPacket();
  }
}

// Read UDP commands from Jetson (data port 8888)
void readUdpCommands() {
  int packetSize = udp.parsePacket();

  if (packetSize == 0) {
    return;
  }

  // Data received - update timestamp
  lastUdpReceiveMs = millis();

  // Read data
  int len = udp.read(udpBuffer, sizeof(udpBuffer) - 1);
  if (len <= 0) {
    return;
  }
  udpBuffer[len] = '\0';

  // Process command buffer (may contain multiple commands)
  for (int i = 0; i < len; i++) {
    char c = udpBuffer[i];

    if (c == '\n') {
      // Null-terminate the command
      cmdBuffer[cmdBufferIndex] = '\0';

      // Process complete command
      if (cmdBufferIndex > 0 && cmdBuffer[0] == 'C' && cmdBuffer[1] == ' ') {
        // Check command rate limit (only for C commands)
        unsigned long now = millis();
        if (now - lastWifiCommandSentMs < MIN_CMD_INTERVAL_MS) {
          // Rate limited - skip this C command
        } else {
          int leftUs = 0, rightUs = 0;
          if (sscanf(cmdBuffer, "C %d %d", &leftUs, &rightUs) == 2) {
            // Constrain and store raw WiFi commands
            int rawL = constrain(leftUs, ESC_MIN, ESC_MAX);
            int rawR = constrain(rightUs, ESC_MIN, ESC_MAX);

            // Apply low-pass filter to WiFi inputs (WiFi uses low-latency filtering)
            int filtL = (wifiAvgL * (100 - WIFI_FILTER_ALPHA) + rawL * WIFI_FILTER_ALPHA) / 100;
            int filtR = (wifiAvgR * (100 - WIFI_FILTER_ALPHA) + rawR * WIFI_FILTER_ALPHA) / 100;

            // Apply soft-start ramp limiting (WiFi uses faster ramp for responsive control)
            int deltaL = filtL - wifiAvgL;
            if (deltaL > WIFI_MAX_STEP_US) deltaL = WIFI_MAX_STEP_US;
            if (deltaL < -WIFI_MAX_STEP_US) deltaL = -WIFI_MAX_STEP_US;
            wifiAvgL += deltaL;

            int deltaR = filtR - wifiAvgR;
            if (deltaR > WIFI_MAX_STEP_US) deltaR = WIFI_MAX_STEP_US;
            if (deltaR < -WIFI_MAX_STEP_US) deltaR = -WIFI_MAX_STEP_US;
            wifiAvgR += deltaR;

            // Smoothed WiFi outputs
            wifiOutL = wifiAvgL;
            wifiOutR = wifiAvgR;
            lastWifiCmdMs = millis();
            lastWifiCommandSentMs = now;
            haveWifiCmd = true;
            lastJetsonPingMs = now;

            Serial.print("UDP Command: Left=");
            Serial.print(wifiOutL);
            Serial.print(" Right=");
            Serial.println(wifiOutR);
          }
        }
      }

      // Reset buffer for next command
      cmdBufferIndex = 0;
    } else if (c != '\r') {
      // Add character to buffer if space available
      if (cmdBufferIndex < CMD_BUFFER_SIZE - 1) {
        cmdBuffer[cmdBufferIndex++] = c;
      } else {
        // Buffer overflow - reset
        cmdBufferIndex = 0;
      }
    }
  }
}

// Read heartbeat ping from Jetson (heartbeat port 8889)
void readHeartbeatPing() {
  int packetSize = udpHeartbeat.parsePacket();
  if (packetSize == 0) {
    return;
  }

  IPAddress remote = udpHeartbeat.remoteIP();

  // Read data
  int len = udpHeartbeat.read(udpBuffer, sizeof(udpBuffer) - 1);
  if (len <= 0) {
    return;
  }
  udpBuffer[len] = '\0';

  // Trim CR/LF
  for (int i = 0; i < len; i++) {
    if (udpBuffer[i] == '\r' || udpBuffer[i] == '\n') {
      udpBuffer[i] = '\0';
      break;
    }
  }

  // Ignore our own broadcast packets
  if (remote == WiFi.localIP()) {
    return;
  }

  if (strcmp(udpBuffer, "PING") == 0 || strcmp(udpBuffer, "P") == 0) {
    lastJetsonPingMs = millis();
  }
}

// Send status via UDP to fixed Jetson address
void sendUdpStatus() {
  unsigned long now = millis();
  if (now - lastStatusSendMs < STATUS_SEND_INTERVAL_MS) {
    return;
  }

  // Only send if WiFi is connected (non-blocking check)
  if (WiFi.status() != WL_CONNECTED) {
    return;
  }
  // Avoid blocking sends when Jetson is offline
  if (!isJetsonOnline(now)) {
    return;
  }

  lastStatusSendMs = now;

  // Send status: "S <mode> <left_us> <right_us>\n"
  char statusBuf[50];
  snprintf(statusBuf, sizeof(statusBuf), "S %d %d %d\n",
           currentMode, currentLeftUs, currentRightUs);

  udp.beginPacket(JETSON_IP, JETSON_PORT);
  udp.print(statusBuf);
  udp.endPacket();
}

// Send flow data via UDP to fixed Jetson address
void sendUdpFlowData() {
  unsigned long now = millis();
  if (now - lastFlowSendMs < FLOW_SEND_INTERVAL_MS) {
    return;
  }

  // Only send if WiFi is connected (non-blocking check)
  if (WiFi.status() != WL_CONNECTED) {
    return;
  }
  // Avoid blocking sends when Jetson is offline
  if (!isJetsonOnline(now)) {
    return;
  }

  lastFlowSendMs = now;

  // Send flow data: "F <freq_hz> <flow_lmin> <velocity_ms> <total_liters>\n"
  char flowBuf[64];
  snprintf(flowBuf, sizeof(flowBuf), "F %.2f %.2f %.4f %.3f\n",
           flowFreqHz, flowLmin, flowVelocity, totalLiters);

  udp.beginPacket(JETSON_IP, JETSON_PORT);
  udp.print(flowBuf);
  udp.endPacket();
}

// Send DHT data via UDP to Jetson
void sendUdpDhtData() {
  unsigned long now = millis();
  if (now - lastDhtSendMs < DHT_SEND_INTERVAL_MS) {
    return;
  }

  if (WiFi.status() != WL_CONNECTED) {
    return;
  }
  if (!isJetsonOnline(now)) {
    return;
  }

  lastDhtSendMs = now;

  // Send DHT data: "D <temp1> <hum1> <temp2> <hum2>\n"
  char dhtBuf[48];
  snprintf(dhtBuf, sizeof(dhtBuf), "D %.2f %.2f %.2f %.2f\n",
           dht1Temperature, dht1Humidity, dht2Temperature, dht2Humidity);

  // Send to Jetson data port (28888)
  udp.beginPacket(JETSON_IP, JETSON_PORT);
  udp.print(dhtBuf);
  udp.endPacket();

  // Also send to monitor port (28889)
  udp.beginPacket(JETSON_IP, MONITOR_HEARTBEAT_PORT);
  udp.print(dhtBuf);
  udp.endPacket();
}

void determineControlMode() {
  unsigned long now = millis();

  bool jetsonOnline = isJetsonOnline(now);
  if (!jetsonOnline) {
    // Jetson offline: immediately favor RC and sync WiFi state to avoid jumps later
    currentMode = 0;
    currentLeftUs = rcOutL;
    currentRightUs = rcOutR;
    wifiAvgL = currentLeftUs;
    wifiAvgR = currentRightUs;
    wifiOutL = wifiAvgL;
    wifiOutR = wifiAvgR;
    haveWifiCmd = false;
    return;
  }

  // Check if WiFi commands are active (recent command received)
  bool udpActive = haveWifiCmd && (now - lastWifiCmdMs < UDP_TIMEOUT_MS);

  if (udpActive) {
    // UDP has priority, preserve smoothing state
    currentMode = 1;
    currentLeftUs = wifiOutL;
    currentRightUs = wifiOutR;
  } else {
    // No recent UDP command — apply grace hold then soft decay
    unsigned long age = haveWifiCmd ? (now - lastWifiCmdMs) : UDP_TIMEOUT_MS + WIFI_GRACE_MS + 1;
    if (age <= UDP_TIMEOUT_MS + WIFI_GRACE_MS) {
      // Hold last UDP filtered values, decay toward neutral
      currentMode = 1;
      currentLeftUs = wifiOutL;
      currentRightUs = wifiOutR;
      if (currentLeftUs > ESC_MID) currentLeftUs -= DECAY_STEP_US; else if (currentLeftUs < ESC_MID) currentLeftUs += DECAY_STEP_US;
      if (currentRightUs > ESC_MID) currentRightUs -= DECAY_STEP_US; else if (currentRightUs < ESC_MID) currentRightUs += DECAY_STEP_US;
      // Keep wifiAvg tracking the decayed values to avoid jumps when UDP resumes
      wifiAvgL = currentLeftUs;
      wifiAvgR = currentRightUs;
      wifiOutL = wifiAvgL;
      wifiOutR = wifiAvgR;
    } else {
      // Fallback to RC after grace expires
      currentMode = 0;
      currentLeftUs = rcOutL;
      currentRightUs = rcOutR;
    }
  }
}

void updateThrusters() {
  escR.writeMicroseconds(currentRightUs);
  escL.writeMicroseconds(currentLeftUs);
}

// === WiFi Multi-Network Management ===

// Try to reconnect to WiFi (attempt previously connected network first)
bool reconnectWiFi() {
  unsigned long now = millis();

  // Wait before reconnect attempt
  if (now - lastWifiDisconnectMs < WIFI_RECONNECT_DELAY_MS) {
    return false;
  }

  Serial.println("\n=== WiFi Reconnection Attempt ===");

  // Try to reconnect to the previously connected network first
  if (currentNetworkIndex >= 0) {
    Serial.print("Reconnecting to: ");
    Serial.println(wifiNetworks[currentNetworkIndex].ssid);

    // Configure IP
    if (!wifiNetworks[currentNetworkIndex].use_dhcp) {
      WiFi.config(wifiNetworks[currentNetworkIndex].local_ip,
                  wifiNetworks[currentNetworkIndex].gateway,
                  wifiNetworks[currentNetworkIndex].subnet);
    }

    // Disconnect first, then attempt reconnection
    WiFi.disconnect();
    delay(100);
    WiFi.begin(wifiNetworks[currentNetworkIndex].ssid,
               wifiNetworks[currentNetworkIndex].password);

    int attempts = 0;
    while (WiFi.status() != WL_CONNECTED && attempts < 10) {
      delay(500);
      Serial.print(".");
      attempts++;
    }

    if (WiFi.status() == WL_CONNECTED) {
      Serial.println("\nReconnected!");
      reconnectAttemptCount = 0;
      reconnectInProgress = false;

      // Restart UDP servers
      udp.begin(UDP_PORT);
      udpHeartbeat.begin(HEARTBEAT_PORT);
      Serial.print("UDP servers restarted on ports ");
      Serial.print(UDP_PORT);
      Serial.print(" (data), ");
      Serial.println(HEARTBEAT_PORT);
      Serial.println(" (heartbeat)");

      return true;
    }

    Serial.println("\nReconnect failed, trying other networks...");
  }

  // If reconnect to previous network failed, try all networks
  reconnectAttemptCount++;
  if (reconnectAttemptCount >= MAX_RECONNECT_ATTEMPTS) {
    Serial.println("Max reconnect attempts reached. Waiting...");
    reconnectInProgress = false;
    reconnectAttemptCount = 0;
    return false;
  }

  // Try all networks in order
  for (int i = 0; i < MAX_WIFI_NETWORKS; i++) {
    // Skip empty entries
    if (wifiNetworks[i].ssid == nullptr || strlen(wifiNetworks[i].ssid) == 0) {
      continue;
    }

    // Skip the network we just tried to reconnect to
    if (i == currentNetworkIndex) {
      continue;
    }

    Serial.print("Trying network [");
    Serial.print(i + 1);
    Serial.print("/");
    Serial.print(MAX_WIFI_NETWORKS);
    Serial.print("]: ");
    Serial.println(wifiNetworks[i].ssid);

    // Configure IP
    if (!wifiNetworks[i].use_dhcp) {
      WiFi.config(wifiNetworks[i].local_ip,
                  wifiNetworks[i].gateway,
                  wifiNetworks[i].subnet);
    } else {
      WiFi.config(IPAddress(0, 0, 0, 0), IPAddress(0, 0, 0, 0), IPAddress(0, 0, 0, 0));
    }

    // Attempt connection
    WiFi.begin(wifiNetworks[i].ssid, wifiNetworks[i].password);

    int attempts = 0;
    while (WiFi.status() != WL_CONNECTED && attempts < 10) {
      delay(500);
      Serial.print(".");
      attempts++;
    }

    if (WiFi.status() == WL_CONNECTED) {
      Serial.println("\nConnected!");
      Serial.print("  Network: ");
      Serial.println(wifiNetworks[i].ssid);
      Serial.print("  IP Address: ");
      Serial.println(WiFi.localIP());
      Serial.print("  RSSI: ");
      Serial.print(WiFi.RSSI());
      Serial.println(" dBm");

      currentNetworkIndex = i;
      reconnectAttemptCount = 0;
      reconnectInProgress = false;

      // Start UDP servers
      udp.begin(UDP_PORT);
      udpHeartbeat.begin(HEARTBEAT_PORT);
      Serial.print("UDP servers started on ports ");
      Serial.print(UDP_PORT);
      Serial.print(" (data), ");
      Serial.println(HEARTBEAT_PORT);
      Serial.println(" (heartbeat)");

      return true;
    }

    WiFi.disconnect();
    delay(500);
  }

  Serial.println("\nAll networks unavailable");
  return false;
}

// Check WiFi status and trigger reconnection if needed
void checkWiFiStatus() {
  unsigned long now = millis();

  // Only check at intervals
  if (now - lastWifiCheckMs < WIFI_CHECK_INTERVAL_MS) {
    return;
  }
  lastWifiCheckMs = now;

  bool wifiConnected = (WiFi.status() == WL_CONNECTED);

  if (!wifiConnected && !reconnectInProgress) {
    // WiFi disconnected - start reconnection process
    if (lastWifiDisconnectMs == 0) {
      lastWifiDisconnectMs = now;
      Serial.println("\nWiFi link lost!");
    }

    reconnectInProgress = true;
    reconnectWiFi();
  } else if (wifiConnected) {
    // WiFi connected - reset disconnect timer
    if (lastWifiDisconnectMs > 0) {
      Serial.println("\nWiFi link restored");
    }
    lastWifiDisconnectMs = 0;
    reconnectInProgress = false;
    reconnectAttemptCount = 0;
  }
}

// Try to connect to WiFi networks in order until successful
bool connectToWiFi() {
  Serial.println("\n=== Attempting WiFi Connection ===");

  for (int i = 0; i < MAX_WIFI_NETWORKS; i++) {
    // Skip empty entries
    if (wifiNetworks[i].ssid == nullptr || strlen(wifiNetworks[i].ssid) == 0) {
      continue;
    }

    Serial.print("Trying network [");
    Serial.print(i + 1);
    Serial.print("/");
    Serial.print(MAX_WIFI_NETWORKS);
    Serial.print("]: ");
    Serial.println(wifiNetworks[i].ssid);

    // Configure IP based on network settings
    if (!wifiNetworks[i].use_dhcp) {
      Serial.print("  Using static IP: ");
      Serial.println(wifiNetworks[i].local_ip);
      WiFi.config(wifiNetworks[i].local_ip, wifiNetworks[i].gateway, wifiNetworks[i].subnet);
    } else {
      Serial.println("  Using DHCP");
      WiFi.config(IPAddress(0, 0, 0, 0), IPAddress(0, 0, 0, 0), IPAddress(0, 0, 0, 0));
    }

    // Attempt connection
    WiFi.begin(wifiNetworks[i].ssid, wifiNetworks[i].password);

    int attempts = 0;
    while (WiFi.status() != WL_CONNECTED && attempts < 20) {
      delay(500);
      Serial.print(".");
      attempts++;
    }

    // Check if connection successful
    if (WiFi.status() == WL_CONNECTED) {
      Serial.println("\nConnected!");
      Serial.print("  Network: ");
      Serial.println(wifiNetworks[i].ssid);
      Serial.print("  IP Address: ");
      Serial.println(WiFi.localIP());
      Serial.print("  Gateway: ");
      Serial.println(WiFi.gatewayIP());
      Serial.print("  Subnet: ");
      Serial.println(WiFi.subnetMask());
      Serial.print("  RSSI: ");
      Serial.print(WiFi.RSSI());
      Serial.println(" dBm");

      currentNetworkIndex = i;
      return true;
    } else {
      Serial.println("\nConnection failed");
    }

    // Disconnect before trying next network
    WiFi.disconnect();
    delay(500);
  }

  Serial.println("\nAll WiFi connection attempts failed");
  currentNetworkIndex = -1;
  return false;
}

// === Setup ===

void setup() {
  // Initialize Serial
  Serial.begin(115200);
  delay(2000);

  Serial.println("\n=== WiFi UDP + RC Thruster Control + Flow Meter ===");
  Serial.print("RC Control Mode: ");
  Serial.println(ENABLE_GEAR_MODE ? "Gear Mode (9 gears, 100µs intervals)" : "Continuous Mode");
  Serial.println();

  // Configure RC input pins
  pinMode(CH_RIGHT_IN, INPUT);
  pinMode(CH_LEFT_IN, INPUT);
  Serial.println("RC input pins configured");

  // Attach interrupts for PWM capture
  attachInterrupt(digitalPinToInterrupt(CH_RIGHT_IN), onRightChange, CHANGE);
  attachInterrupt(digitalPinToInterrupt(CH_LEFT_IN), onLeftChange, CHANGE);
  Serial.println("RC interrupts attached");

  // Configure flow meter pin
  pinMode(FLOW_SENSOR_PIN, INPUT_PULLUP);
  lastFlowState = digitalRead(FLOW_SENSOR_PIN);
  Serial.println("Flow meter sensor configured on D7");

  // Initialize DHT sensors
  dht1.begin();
  dht2.begin();
  Serial.println("DHT22 sensors configured on D12 and D13");

  // Connect to WiFi (try all networks in order)
  bool wifiConnected = connectToWiFi();

  if (wifiConnected) {
    // Start data UDP server (commands, status, flow)
    udp.begin(UDP_PORT);
    Serial.print("Data UDP server started on port ");
    Serial.println(UDP_PORT);

    // Start heartbeat UDP server
    udpHeartbeat.begin(HEARTBEAT_PORT);
    Serial.print("Heartbeat server started on port ");
    Serial.println(HEARTBEAT_PORT);
    Serial.println("Ready for UDP control commands");
  } else {
    Serial.println("WiFi unavailable - Running in RC only mode");
  }

  // Initialize ESCs
  escL.attach(ESC_LEFT_OUT);
  escR.attach(ESC_RIGHT_OUT);

  // ESC calibration - neutral for 2 seconds
  escL.writeMicroseconds(ESC_MID);
  escR.writeMicroseconds(ESC_MID);
  Serial.println("ESCs initialized to neutral (1500 µs)");
  delay(2000);

  Serial.println("\n=== System Ready ===");
  Serial.println("Control Priority: UDP > RC > Failsafe");
  Serial.println("Flow Meter: D7 polling mode, 1 Hz update rate");
  Serial.println("DHT22: D12 and D13, 1 Hz update rate");
  Serial.println("UDP: Listen 8888, Send S/F/D to 192.168.50.200:28888");
  Serial.println("     DHT also sent to 192.168.50.200:28889 (monitor)");
  Serial.println("     HEARTBEAT broadcast to 192.168.50.255:8889");
  Serial.println("     HEARTBEAT unicast to 192.168.50.200:28887 (Jetson)");
  Serial.println();
}

// === Main Loop ===

void loop() {
  unsigned long now = millis();

  // 0. Poll flow sensor (lightweight, high frequency)
  pollFlowSensor();

  // 1. Check WiFi status and auto-reconnect if needed
  checkWiFiStatus();

  // 2. Poll again after WiFi check (may have missed pulses)
  pollFlowSensor();

  // 3. Read RC inputs (non-blocking with interrupts)
  readRcInputs();

  // 4. Read UDP commands (may block!)
  readUdpCommands();

  // 5. Read heartbeat ping (UDP 8889)
  readHeartbeatPing();

  // 6. Poll again after UDP read (critical - UDP can block)
  pollFlowSensor();

  // 7. Send heartbeat (may block!)
  sendHeartbeat();

  // 8. Poll again after heartbeat
  pollFlowSensor();

  // 9. Determine control mode and outputs (fast)
  determineControlMode();

  // 10. Update thrusters (fast)
  updateThrusters();

  // 11. Send status to Jetson (may block!)
  sendUdpStatus();

  // 12. Poll again after status send
  pollFlowSensor();

  // 13. Send flow data to Jetson (may block!)
  sendUdpFlowData();

  // 13.5. Read and send DHT data
  readDhtSensor(now);
  sendUdpDhtData();

  // 14. Final poll before loop restart
  pollFlowSensor();

  // 15. Calculate flow data (do this once per loop)
  calculateFlowData(now);

  // 16. Connection state transitions (fast)
  bool wifiLink = (WiFi.status() == WL_CONNECTED);
  static bool prevWifiLink = false;
  static bool stateInit = false;
  if (!stateInit) {
    prevWifiLink = wifiLink;
    stateInit = true;
  }
  if (wifiLink != prevWifiLink) {
    Serial.print("WiFi link ");
    Serial.println(wifiLink ? "CONNECTED" : "DISCONNECTED");
    prevWifiLink = wifiLink;
  }

  // Debug: Print WiFi command age
  static unsigned long lastDebugMs = 0;
  if (now - lastDebugMs >= 1000) {  // Print every 1 second
    unsigned long cmdAge = haveWifiCmd ? (now - lastWifiCmdMs) : 0;
    Serial.print("WiFi cmd age: ");
    Serial.print(cmdAge);
    Serial.print(" ms | Mode: ");
    Serial.println(currentMode == 1 ? "WiFi" : "RC");
    lastDebugMs = now;
  }
}
