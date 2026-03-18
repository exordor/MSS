#include <WiFiS3.h>
#include "Arduino_LED_Matrix.h"
#include "pwm.h"
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
 *   - Arduino Send to: 192.168.50.200:28889 (S status, F flow, D dht, HEARTBEAT to Monitor) [optional]
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
 *   - Monitor node: Receives S/F/D on 28889, HEARTBEAT on 28889 (optional)
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
const unsigned long WIFI_CHECK_INTERVAL_MS = 250;   // Background WiFi state machine tick
const unsigned long WIFI_RECONNECT_DELAY_MS = 5000; // Wait 5s before reconnect attempt
const int MAX_RECONNECT_ATTEMPTS = 3;               // Max full background scan cycles before pausing
const unsigned long WIFI_CONNECT_ATTEMPT_TIMEOUT_MS = 10000; // Per-network connection timeout
const unsigned long WIFI_UDP_START_DELAY_MS = 300;  // Let the network stack settle briefly before binding UDP sockets
const unsigned long UDP_START_RETRY_INTERVAL_MS = 1000; // Avoid tight begin()/stop() churn if sockets are not ready yet
unsigned long lastWifiCheckMs = 0;
unsigned long lastWifiDisconnectMs = 0;
unsigned long wifiConnectedAtMs = 0;
unsigned long lastUdpStartAttemptMs = 0;
int reconnectAttemptCount = 0;
bool reconnectInProgress = false;
bool wifiAttemptActive = false;
unsigned long wifiAttemptStartMs = 0;
int wifiAttemptNetworkIndex = -1;
int wifiCycleStartIndex = -1;
int wifiNetworksTriedThisCycle = 0;
bool udpServersStarted = false;
bool cachedWifiConnected = false;

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
const bool ENABLE_DHT_SENSORS = true;                     // Safe with hardware PWM ESC output on UNO R4
const byte DHT_PIN_1 = 12;                             // D12 for DHT22 #1 data
const byte DHT_PIN_2 = 13;                             // D13 for DHT22 #2 data
#define DHT_TYPE DHT22
const unsigned long DHT_READ_INTERVAL_MS = 2500;       // DHT22 max 0.5 Hz
const unsigned long DHT_SEND_INTERVAL_MS = 1000;       // 1 Hz UDP send rate

// === Timing Constants ===
// Debug level: 0=Minimal (errors only), 1=Basic (sensors+status), 2=Verbose (all UDP)
#define DEBUG_LEVEL 1
const bool PWM_DEBUG_ENABLED = false;               // Dedicated PWM debug stream for RC/WiFi/ESC investigation
const unsigned long PWM_DEBUG_INTERVAL_MS = 100;   // 10 Hz so brief twitches are still visible on Serial
const bool PWM_EVENT_DEBUG_ENABLED = true;         // Print immediately when commanded ESC output changes

const unsigned long RC_FAILSAFE_MS = 200;            // RC signal timeout
const unsigned long UDP_TIMEOUT_MS = 2000;           // UDP timeout (2s without data = offline)
const unsigned long JETSON_ONLINE_TIMEOUT_MS = 2000; // Jetson online if ping/command seen recently
const unsigned long HEARTBEAT_INTERVAL_MS = 1000;    // Heartbeat send interval (1 second, broadcast mode)
const unsigned long WIFI_GRACE_MS = 400;             // Hold-last grace after timeout
const int DECAY_STEP_US = 5;                         // Soft decay step toward 1500
const unsigned long STATUS_SEND_INTERVAL_MS = 100;   // Status update rate (10Hz)
const unsigned long MONITOR_SEND_INTERVAL_MS = 1000;  // Monitor port update rate (1Hz)
const unsigned long MONITOR_PACKET_INTERVAL_MS = (MONITOR_SEND_INTERVAL_MS + 2) / 3; // Stagger S/F/D across loops at ~1 Hz each

// === WiFi LED Matrix Indicator ===
const unsigned long WIFI_MATRIX_BLINK_INTERVAL_MS = 120;
uint8_t WIFI_MATRIX_ICON[8][12] = {
  {0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0},
  {0, 0, 0, 1, 1, 1, 1, 1, 1, 0, 0, 0},
  {0, 0, 1, 0, 0, 0, 0, 0, 0, 1, 0, 0},
  {0, 0, 0, 0, 1, 1, 1, 1, 0, 0, 0, 0},
  {0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0},
  {0, 0, 0, 0, 0, 1, 1, 0, 0, 0, 0, 0},
  {0, 0, 0, 0, 0, 1, 1, 0, 0, 0, 0, 0},
  {0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0}
};
uint8_t WIFI_MATRIX_OFF[8][12] = {
  {0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0},
  {0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0},
  {0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0},
  {0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0},
  {0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0},
  {0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0},
  {0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0},
  {0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0}
};

// === ESC Configuration ===
const int RX_VALID_MIN = 950;
const int RX_VALID_MAX = 2000;
const int ESC_MIN = 1100;
const int ESC_MID = 1500;
const int ESC_MAX = 1900;
const unsigned long ESC_PWM_PERIOD_US = 20000;           // 50 Hz ESC update period
const unsigned long ESC_SAFE_BOOT_NEUTRAL_MS = 2000; // Hold neutral briefly on boot so ESCs can arm before control starts
const int DEADBAND_US = 40;  // Increased deadband to resist joystick drift (±40µs around center)
const int RC_EXIT_NEUTRAL_DEADBAND_US = 70;   // Must move this far from 1500 before RC can leave neutral
const int RC_RETURN_NEUTRAL_DEADBAND_US = 45; // Return-to-neutral hysteresis for RC input
const int ESC_NEUTRAL_SNAP_US = 12;           // Clamp tiny residual output changes back to exact neutral
const byte RC_OFFCENTER_CONFIRM_FRAMES = 2;   // Require consecutive off-center RC frames before motion

// === ESC PWM Outputs ===
PwmOut escL(ESC_LEFT_OUT);
PwmOut escR(ESC_RIGHT_OUT);
ArduinoLEDMatrix ledMatrix;
bool escPwmInitialized = false;
bool ledMatrixInitialized = false;
bool wifiMatrixBlinkVisible = false;
unsigned long lastWifiMatrixBlinkMs = 0;

// === RC State Variables ===
// RC state - interrupt-based capture
volatile unsigned long rRiseMicros = 0, rPulseMicros = 0;
volatile unsigned long lRiseMicros = 0, lPulseMicros = 0;
volatile unsigned long rPulseCapturedAtUs = 0;
volatile unsigned long lPulseCapturedAtUs = 0;
unsigned long lastRcUpdateL = 0;
unsigned long lastRcUpdateR = 0;
byte rcOffcenterFramesL = 0;
byte rcOffcenterFramesR = 0;
bool rcMotionLatchedL = false;
bool rcMotionLatchedR = false;

// RC filtering and smoothing (separate from WiFi for different response characteristics)
int rcAvgL = ESC_MID;
int rcAvgR = ESC_MID;
const int RC_FILTER_ALPHA = 25;       // RC filter (25% = smooth, resists joystick drift)
const int RC_MAX_STEP_US = 15;        // RC ramp limiting (15µs per cycle = smooth RC control)
const unsigned long RC_SIGNAL_TIMEOUT_US = RC_FAILSAFE_MS * 1000UL;

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

enum MonitorPacketType : byte {
  MONITOR_PACKET_STATUS = 0,
  MONITOR_PACKET_FLOW = 1,
  MONITOR_PACKET_DHT = 2,
  MONITOR_PACKET_COUNT = 3
};

enum UdpSendTask : byte {
  UDP_SEND_TASK_HEARTBEAT = 0,
  UDP_SEND_TASK_STATUS = 1,
  UDP_SEND_TASK_FLOW = 2,
  UDP_SEND_TASK_DHT = 3,
  UDP_SEND_TASK_MONITOR = 4,
  UDP_SEND_TASK_COUNT = 5
};

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
unsigned long lastMonitorSendMs = 0 - MONITOR_PACKET_INTERVAL_MS;  // Allow immediate first send

// === Flow Meter State ===
unsigned long lastFlowCalcMs = 0;     // Last time flow data was calculated
unsigned long lastFlowSendMs = 0 - FLOW_SEND_INTERVAL_MS;  // Allow immediate first send
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
unsigned long lastDhtReadMs = 0 - DHT_READ_INTERVAL_MS;  // Allow immediate first read
unsigned long lastDhtSendMs = 0 - DHT_SEND_INTERVAL_MS;  // Allow immediate first send
byte nextMonitorPacketType = 0;
byte nextUdpSendTask = 0;

// === Helper Functions ===

inline bool isJetsonOnline(unsigned long now) {
  return (lastJetsonPingMs > 0) && (now - lastJetsonPingMs < JETSON_ONLINE_TIMEOUT_MS);
}

bool initEscPwmOutputs() {
  bool leftOk = escL.begin(ESC_PWM_PERIOD_US, ESC_MID);
  bool rightOk = escR.begin(ESC_PWM_PERIOD_US, ESC_MID);
  escPwmInitialized = leftOk && rightOk;
  return escPwmInitialized;
}

// Right channel interrupt handler
void onRightChange() {
  int level = digitalRead(CH_RIGHT_IN);
  unsigned long now = micros();
  if (level == HIGH) {
    rRiseMicros = now;
  } else {
    unsigned long width = now - rRiseMicros;
    // Only accept real RC PWM pulse widths.
    if (width >= RX_VALID_MIN && width <= RX_VALID_MAX) {
      rPulseMicros = width;
      rPulseCapturedAtUs = now;
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
    if (width >= RX_VALID_MIN && width <= RX_VALID_MAX) {
      lPulseMicros = width;
      lPulseCapturedAtUs = now;
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

unsigned long applyRcNeutralHysteresis(unsigned long pulseUs, bool &motionLatched, byte &offcenterFrames) {
  if (pulseUs == 0) {
    motionLatched = false;
    offcenterFrames = 0;
    return 0;
  }

  int deltaUs = abs((int)pulseUs - ESC_MID);

  if (motionLatched) {
    if (deltaUs <= RC_RETURN_NEUTRAL_DEADBAND_US) {
      motionLatched = false;
      offcenterFrames = 0;
      return ESC_MID;
    }
    return pulseUs;
  }

  if (deltaUs <= RC_EXIT_NEUTRAL_DEADBAND_US) {
    offcenterFrames = 0;
    return ESC_MID;
  }

  if (offcenterFrames < RC_OFFCENTER_CONFIRM_FRAMES) {
    offcenterFrames++;
  }

  if (offcenterFrames < RC_OFFCENTER_CONFIRM_FRAMES) {
    return ESC_MID;
  }

  motionLatched = true;
  return pulseUs;
}

int snapEscToNeutral(int pulseUs) {
  if (abs(pulseUs - ESC_MID) <= ESC_NEUTRAL_SNAP_US) {
    return ESC_MID;
  }
  return constrain(pulseUs, ESC_MIN, ESC_MAX);
}

void printPwmDebug(unsigned long now) {
  if (!PWM_DEBUG_ENABLED) {
    return;
  }

  static unsigned long lastPwmDebugMs = 0;
  if (now - lastPwmDebugMs < PWM_DEBUG_INTERVAL_MS) {
    return;
  }
  lastPwmDebugMs = now;

  unsigned long rawR = 0;
  unsigned long rawL = 0;
  unsigned long captureRUs = 0;
  unsigned long captureLUs = 0;

  noInterrupts();
  rawR = rPulseMicros;
  rawL = lPulseMicros;
  captureRUs = rPulseCapturedAtUs;
  captureLUs = lPulseCapturedAtUs;
  interrupts();

  bool freshR = (captureRUs > 0) && (micros() - captureRUs <= RC_SIGNAL_TIMEOUT_US);
  bool freshL = (captureLUs > 0) && (micros() - captureLUs <= RC_SIGNAL_TIMEOUT_US);
  unsigned long ageRUs = freshR ? (micros() - captureRUs) : 0;
  unsigned long ageLUs = freshL ? (micros() - captureLUs) : 0;

  Serial.print("[PWM] mode=");
  Serial.print(currentMode == 1 ? "WiFi" : "RC");
  Serial.print(" rawL=");
  Serial.print(rawL);
  Serial.print(" rawR=");
  Serial.print(rawR);
  Serial.print(" freshL=");
  Serial.print(freshL ? 1 : 0);
  Serial.print(" freshR=");
  Serial.print(freshR ? 1 : 0);
  Serial.print(" ageL_us=");
  Serial.print(ageLUs);
  Serial.print(" ageR_us=");
  Serial.print(ageRUs);
  Serial.print(" latchL=");
  Serial.print(rcMotionLatchedL ? 1 : 0);
  Serial.print(" latchR=");
  Serial.print(rcMotionLatchedR ? 1 : 0);
  Serial.print(" rcL=");
  Serial.print(rcOutL);
  Serial.print(" rcR=");
  Serial.print(rcOutR);
  Serial.print(" wifiL=");
  Serial.print(wifiOutL);
  Serial.print(" wifiR=");
  Serial.print(wifiOutR);
  Serial.print(" outL=");
  Serial.print(currentLeftUs);
  Serial.print(" outR=");
  Serial.println(currentRightUs);
}

void printPwmEventDebug() {
  if (!PWM_EVENT_DEBUG_ENABLED) {
    return;
  }

  static bool initialized = false;
  static int lastOutL = ESC_MID;
  static int lastOutR = ESC_MID;
  static int lastMode = 0;

  if (!initialized) {
    lastOutL = currentLeftUs;
    lastOutR = currentRightUs;
    lastMode = currentMode;
    initialized = true;
    return;
  }

  if (currentLeftUs == lastOutL && currentRightUs == lastOutR && currentMode == lastMode) {
    return;
  }

  Serial.print("[PWM EVT] mode=");
  Serial.print(currentMode == 1 ? "WiFi" : "RC");
  Serial.print(" prevL=");
  Serial.print(lastOutL);
  Serial.print(" prevR=");
  Serial.print(lastOutR);
  Serial.print(" newL=");
  Serial.print(currentLeftUs);
  Serial.print(" newR=");
  Serial.println(currentRightUs);

  lastOutL = currentLeftUs;
  lastOutR = currentRightUs;
  lastMode = currentMode;
}

void renderWifiStatusMatrix(bool lit) {
  if (!ledMatrixInitialized) {
    return;
  }

  if (lit) {
    ledMatrix.renderBitmap(WIFI_MATRIX_ICON, 8, 12);
  } else {
    ledMatrix.renderBitmap(WIFI_MATRIX_OFF, 8, 12);
  }
}

void updateWifiStatusMatrix(unsigned long now, bool wifiConnected) {
  if (!ledMatrixInitialized) {
    return;
  }

  enum WifiMatrixMode {
    WIFI_MATRIX_MODE_OFF = 0,
    WIFI_MATRIX_MODE_BLINK = 1,
    WIFI_MATRIX_MODE_SOLID = 2
  };
  static int lastMode = WIFI_MATRIX_MODE_OFF;

  bool shouldBlink = !wifiConnected &&
                     countConfiguredWifiNetworks() > 0 &&
                     (wifiAttemptActive || reconnectInProgress || lastWifiDisconnectMs > 0);

  if (wifiConnected) {
    if (lastMode != WIFI_MATRIX_MODE_SOLID) {
      renderWifiStatusMatrix(true);
      wifiMatrixBlinkVisible = true;
    }
    lastMode = WIFI_MATRIX_MODE_SOLID;
    return;
  }

  if (!shouldBlink) {
    if (lastMode != WIFI_MATRIX_MODE_OFF) {
      renderWifiStatusMatrix(false);
      wifiMatrixBlinkVisible = false;
    }
    lastMode = WIFI_MATRIX_MODE_OFF;
    return;
  }

  if (lastMode != WIFI_MATRIX_MODE_BLINK) {
    wifiMatrixBlinkVisible = true;
    lastWifiMatrixBlinkMs = now;
    renderWifiStatusMatrix(true);
    lastMode = WIFI_MATRIX_MODE_BLINK;
    return;
  }

  if (now - lastWifiMatrixBlinkMs >= WIFI_MATRIX_BLINK_INTERVAL_MS) {
    wifiMatrixBlinkVisible = !wifiMatrixBlinkVisible;
    lastWifiMatrixBlinkMs = now;
    renderWifiStatusMatrix(wifiMatrixBlinkVisible);
  }
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
  unsigned long nowUs = micros();

  // Read pulse widths from interrupt capture (non-blocking)
  noInterrupts();
  unsigned long inR = rPulseMicros;
  unsigned long inL = lPulseMicros;
  unsigned long captureRUs = rPulseCapturedAtUs;
  unsigned long captureLUs = lPulseCapturedAtUs;
  interrupts();

  bool rcFreshR = (captureRUs > 0) && (nowUs - captureRUs <= RC_SIGNAL_TIMEOUT_US);
  bool rcFreshL = (captureLUs > 0) && (nowUs - captureLUs <= RC_SIGNAL_TIMEOUT_US);

  // Only trust pulses that were captured recently; stale widths must not keep RC alive forever.
  if (rcFreshR && inR >= RX_VALID_MIN && inR <= RX_VALID_MAX) {
    lastRcUpdateR = now;
  } else {
    inR = 0;
  }
  if (rcFreshL && inL >= RX_VALID_MIN && inL <= RX_VALID_MAX) {
    lastRcUpdateL = now;
  } else {
    inL = 0;
  }

  inR = applyRcNeutralHysteresis(inR, rcMotionLatchedR, rcOffcenterFramesR);
  inL = applyRcNeutralHysteresis(inL, rcMotionLatchedL, rcOffcenterFramesL);

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

// Calculate flow rate at specified interval (1s window for accurate pulse counting)
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
    flowLmin = freqHz / K_HZ_PER_LMIN;

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
  if (!ENABLE_DHT_SENSORS) {
    return;
  }
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

void markUdpTransportFailure(const char* context) {
  Serial.print("UDP transport failed: ");
  Serial.println(context);
  stopUdpServers();
  lastUdpStartAttemptMs = 0;
}

bool sendUdpPacket(WiFiUDP& socket, const IPAddress& ip, uint16_t port, const char* payload, const char* context) {
  size_t payloadLen = strlen(payload);
  if (!socket.beginPacket(ip, port)) {
    markUdpTransportFailure(context);
    return false;
  }
  if (socket.write((const uint8_t*)payload, payloadLen) != payloadLen) {
    markUdpTransportFailure(context);
    return false;
  }
  if (!socket.endPacket()) {
    markUdpTransportFailure(context);
    return false;
  }
  return true;
}

// Send heartbeat to Jetson (fixed address, unicast)
bool sendHeartbeat(unsigned long now, bool wifiConnected) {
  if (now - lastHeartbeatMs < HEARTBEAT_INTERVAL_MS) {
    return false;
  }
  if (!udpServersStarted || !wifiConnected) {
    return false;
  }

  if (ENABLE_HEARTBEAT_BROADCAST &&
      !sendUdpPacket(udpHeartbeat, HEARTBEAT_BROADCAST_IP, HEARTBEAT_PORT, "HEARTBEAT\n", "heartbeat broadcast")) {
    return false;
  }

  // Send unicast heartbeats only when Jetson is online to avoid blocking
  if (isJetsonOnline(now) &&
      !sendUdpPacket(udpHeartbeat, JETSON_IP, JETSON_HEARTBEAT_PORT, "HEARTBEAT\n", "heartbeat unicast")) {
    return false;
  }

  lastHeartbeatMs = now;
  return true;
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

            // Debug: Show received command (rate limited to prevent flooding)
            static unsigned long lastUdpDebugMs = 0;
            if (DEBUG_LEVEL >= 2 && now - lastUdpDebugMs >= 200) {  // Max 5 Hz output
              lastUdpDebugMs = now;
              Serial.print("[UDP CMD] L=");
              Serial.print(wifiOutL);
              Serial.print(" R=");
              Serial.println(wifiOutR);
            }
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
bool sendUdpStatus(unsigned long now, bool wifiConnected) {
  if (now - lastStatusSendMs < STATUS_SEND_INTERVAL_MS) {
    return false;
  }
  if (!udpServersStarted || !wifiConnected) {
    return false;
  }
  if (!isJetsonOnline(now)) {
    return false;
  }

  // Send status: "S <mode> <left_us> <right_us>\n"
  char statusBuf[50];
  snprintf(statusBuf, sizeof(statusBuf), "S %d %d %d\n",
           currentMode, currentLeftUs, currentRightUs);

  // Send to Jetson data port (28888) - 10 Hz
  if (!sendUdpPacket(udp, JETSON_IP, JETSON_PORT, statusBuf, "status")) {
    return false;
  }

  lastStatusSendMs = now;
  return true;
}

// Send flow data via UDP to fixed Jetson address
bool sendUdpFlowData(unsigned long now, bool wifiConnected) {
  if (now - lastFlowSendMs < FLOW_SEND_INTERVAL_MS) {
    return false;
  }
  if (!udpServersStarted || !wifiConnected) {
    return false;
  }
  if (!isJetsonOnline(now)) {
    return false;
  }

  // Send flow data: "F <freq_hz> <flow_lmin> <velocity_ms> <total_liters>\n"
  char flowBuf[64];
  snprintf(flowBuf, sizeof(flowBuf), "F %.2f %.2f %.4f %.3f\n",
           flowFreqHz, flowLmin, flowVelocity, totalLiters);

  // Send to Jetson data port (28888) - 5 Hz
  if (!sendUdpPacket(udp, JETSON_IP, JETSON_PORT, flowBuf, "flow")) {
    return false;
  }

  lastFlowSendMs = now;
  return true;
}

// Send DHT data via UDP to Jetson
bool sendUdpDhtData(unsigned long now, bool wifiConnected) {
  if (!ENABLE_DHT_SENSORS) {
    return false;
  }
  if (now - lastDhtSendMs < DHT_SEND_INTERVAL_MS) {
    return false;
  }
  if (!udpServersStarted || !wifiConnected) {
    return false;
  }
  if (!isJetsonOnline(now)) {
    return false;
  }

  // Send DHT data: "D <temp1> <hum1> <temp2> <hum2>\n"
  char dhtBuf[48];
  snprintf(dhtBuf, sizeof(dhtBuf), "D %.2f %.2f %.2f %.2f\n",
           dht1Temperature, dht1Humidity, dht2Temperature, dht2Humidity);

  // Send to Jetson data port (28888) - 1 Hz
  if (!sendUdpPacket(udp, JETSON_IP, JETSON_PORT, dhtBuf, "dht")) {
    return false;
  }

  lastDhtSendMs = now;
  return true;
}

// Send monitor packets one-at-a-time so a single loop never bursts three UDP sends back-to-back.
bool sendToMonitorPort(unsigned long now, bool wifiConnected) {
  if (now - lastMonitorSendMs < MONITOR_PACKET_INTERVAL_MS) {
    return false;
  }
  if (!udpServersStarted || !wifiConnected) {
    return false;
  }
  if (!isJetsonOnline(now)) {
    return false;
  }

  char packetBuf[64];
  const char* context = "monitor";

  switch (nextMonitorPacketType) {
    case MONITOR_PACKET_STATUS:
      snprintf(packetBuf, sizeof(packetBuf), "S %d %d %d\n",
               currentMode, currentLeftUs, currentRightUs);
      context = "monitor status";
      break;
    case MONITOR_PACKET_FLOW:
      snprintf(packetBuf, sizeof(packetBuf), "F %.2f %.2f %.4f %.3f\n",
               flowFreqHz, flowLmin, flowVelocity, totalLiters);
      context = "monitor flow";
      break;
    case MONITOR_PACKET_DHT:
    default:
      snprintf(packetBuf, sizeof(packetBuf), "D %.2f %.2f %.2f %.2f\n",
               dht1Temperature, dht1Humidity, dht2Temperature, dht2Humidity);
      context = "monitor dht";
      break;
  }

  if (!sendUdpPacket(udp, JETSON_IP, MONITOR_HEARTBEAT_PORT, packetBuf, context)) {
    return false;
  }

  lastMonitorSendMs = now;
  nextMonitorPacketType = (nextMonitorPacketType + 1) % MONITOR_PACKET_COUNT;
  return true;
}

void serviceOneUdpSendTask(unsigned long now, bool wifiConnected) {
  for (byte offset = 0; offset < UDP_SEND_TASK_COUNT; ++offset) {
    byte task = (nextUdpSendTask + offset) % UDP_SEND_TASK_COUNT;
    bool sent = false;

    switch (task) {
      case UDP_SEND_TASK_HEARTBEAT:
        sent = sendHeartbeat(now, wifiConnected);
        break;
      case UDP_SEND_TASK_STATUS:
        sent = sendUdpStatus(now, wifiConnected);
        break;
      case UDP_SEND_TASK_FLOW:
        sent = sendUdpFlowData(now, wifiConnected);
        break;
      case UDP_SEND_TASK_DHT:
        sent = sendUdpDhtData(now, wifiConnected);
        break;
      case UDP_SEND_TASK_MONITOR:
        sent = sendToMonitorPort(now, wifiConnected);
        break;
      default:
        break;
    }

    if (sent) {
      nextUdpSendTask = (task + 1) % UDP_SEND_TASK_COUNT;
      return;
    }
    if (!udpServersStarted) {
      return;
    }
  }
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
  currentRightUs = snapEscToNeutral(currentRightUs);
  currentLeftUs = snapEscToNeutral(currentLeftUs);
  if (escPwmInitialized) {
    escR.pulseWidth_us(currentRightUs);
    escL.pulseWidth_us(currentLeftUs);
  }
}

// === WiFi Multi-Network Management ===

bool isWifiNetworkConfigured(int index) {
  return index >= 0 &&
         index < MAX_WIFI_NETWORKS &&
         wifiNetworks[index].ssid != nullptr &&
         strlen(wifiNetworks[index].ssid) > 0;
}

int countConfiguredWifiNetworks() {
  int count = 0;
  for (int i = 0; i < MAX_WIFI_NETWORKS; i++) {
    if (isWifiNetworkConfigured(i)) {
      count++;
    }
  }
  return count;
}

int findFirstConfiguredWifiNetwork() {
  for (int i = 0; i < MAX_WIFI_NETWORKS; i++) {
    if (isWifiNetworkConfigured(i)) {
      return i;
    }
  }
  return -1;
}

int findNextConfiguredWifiNetwork(int startAfter) {
  for (int offset = 1; offset <= MAX_WIFI_NETWORKS; offset++) {
    int idx = (startAfter + offset + MAX_WIFI_NETWORKS) % MAX_WIFI_NETWORKS;
    if (isWifiNetworkConfigured(idx)) {
      return idx;
    }
  }
  return -1;
}

void configureWifiForNetwork(int index) {
  if (!isWifiNetworkConfigured(index)) {
    return;
  }

  if (!wifiNetworks[index].use_dhcp) {
    Serial.print("  Using static IP: ");
    Serial.println(wifiNetworks[index].local_ip);
    // WiFiS3 uses config(local_ip, dns_server, gateway, subnet).
    // Reuse the router IP as DNS so local static-IP links still get a valid gateway.
    WiFi.config(wifiNetworks[index].local_ip,
                wifiNetworks[index].gateway,
                wifiNetworks[index].gateway,
                wifiNetworks[index].subnet);
  } else {
    Serial.println("  Using DHCP");
    WiFi.config(IPAddress(0, 0, 0, 0));
  }
}

void printWifiConnectedInfo(int index) {
  Serial.println("\nWiFi connected");
  if (isWifiNetworkConfigured(index)) {
    Serial.print("  Network: ");
    Serial.println(wifiNetworks[index].ssid);
  }
  Serial.print("  IP Address: ");
  Serial.println(WiFi.localIP());
  Serial.print("  Gateway: ");
  Serial.println(WiFi.gatewayIP());
  Serial.print("  Subnet: ");
  Serial.println(WiFi.subnetMask());
  Serial.print("  RSSI: ");
  Serial.print(WiFi.RSSI());
  Serial.println(" dBm");
}

void stopUdpServers() {
  udp.stop();
  udpHeartbeat.stop();
  udpServersStarted = false;
}

void ensureUdpServersStarted(unsigned long now, bool wifiConnected) {
  if (udpServersStarted || !wifiConnected) {
    return;
  }

  if (wifiConnectedAtMs == 0) {
    wifiConnectedAtMs = now;
  }
  if (now - wifiConnectedAtMs < WIFI_UDP_START_DELAY_MS) {
    return;
  }
  if (lastUdpStartAttemptMs != 0 && now - lastUdpStartAttemptMs < UDP_START_RETRY_INTERVAL_MS) {
    return;
  }

  lastUdpStartAttemptMs = now;

  // WiFiS3 latches a socket handle after begin(); if one port succeeds and the
  // other fails, we must stop both before retrying or begin() will keep returning 0.
  stopUdpServers();

  uint8_t dataOk = udp.begin(UDP_PORT);
  uint8_t heartbeatOk = udpHeartbeat.begin(HEARTBEAT_PORT);
  if (!dataOk || !heartbeatOk) {
    stopUdpServers();
    Serial.print("UDP start failed, retrying: data=");
    Serial.print((int)dataOk);
    Serial.print(" heartbeat=");
    Serial.println((int)heartbeatOk);
    return;
  }

  udpServersStarted = true;
  lastUdpStartAttemptMs = 0;

  Serial.print("Data UDP server started on port ");
  Serial.println(UDP_PORT);
  Serial.print("Heartbeat server started on port ");
  Serial.println(HEARTBEAT_PORT);
  Serial.println("Ready for UDP control commands");
}

void resetWifiAttemptState() {
  wifiAttemptActive = false;
  wifiAttemptStartMs = 0;
  wifiAttemptNetworkIndex = -1;
  wifiCycleStartIndex = -1;
  wifiNetworksTriedThisCycle = 0;
}

void startWifiAttempt(int index, unsigned long now) {
  if (!isWifiNetworkConfigured(index)) {
    return;
  }

  int configuredCount = countConfiguredWifiNetworks();
  wifiAttemptActive = true;
  wifiAttemptStartMs = now;
  wifiAttemptNetworkIndex = index;

  Serial.print("WiFi connect attempt [");
  Serial.print(wifiNetworksTriedThisCycle + 1);
  Serial.print("/");
  Serial.print(configuredCount);
  Serial.print("]: ");
  Serial.println(wifiNetworks[index].ssid);

  WiFi.disconnect();
  configureWifiForNetwork(index);
  WiFi.begin(wifiNetworks[index].ssid, wifiNetworks[index].password);
}

bool startNextWifiAttempt(unsigned long now) {
  int configuredCount = countConfiguredWifiNetworks();
  if (configuredCount == 0 || wifiNetworksTriedThisCycle >= configuredCount) {
    return false;
  }

  int nextIndex = wifiAttemptNetworkIndex;
  if (wifiNetworksTriedThisCycle == 0) {
    nextIndex = wifiCycleStartIndex;
  } else {
    nextIndex = findNextConfiguredWifiNetwork(wifiAttemptNetworkIndex);
  }

  if (!isWifiNetworkConfigured(nextIndex)) {
    return false;
  }

  startWifiAttempt(nextIndex, now);
  return true;
}

void beginWifiReconnectCycle(unsigned long now, bool immediate) {
  int configuredCount = countConfiguredWifiNetworks();
  if (configuredCount == 0) {
    currentNetworkIndex = -1;
    reconnectInProgress = false;
    resetWifiAttemptState();
    return;
  }

  reconnectInProgress = true;
  wifiCycleStartIndex = isWifiNetworkConfigured(currentNetworkIndex)
                          ? currentNetworkIndex
                          : findFirstConfiguredWifiNetwork();
  wifiAttemptNetworkIndex = -1;
  wifiNetworksTriedThisCycle = 0;
  wifiAttemptActive = false;
  wifiAttemptStartMs = 0;

  Serial.println("\n=== WiFi Background Connect ===");
  wifiMatrixBlinkVisible = true;
  lastWifiMatrixBlinkMs = now;
  renderWifiStatusMatrix(true);
  if (immediate) {
    startNextWifiAttempt(now);
  }
}

void finishWifiReconnectCycle(unsigned long now) {
  reconnectInProgress = false;
  resetWifiAttemptState();
  reconnectAttemptCount++;
  lastWifiDisconnectMs = now;

  if (reconnectAttemptCount >= MAX_RECONNECT_ATTEMPTS) {
    Serial.print("WiFi unavailable after ");
    Serial.print(MAX_RECONNECT_ATTEMPTS);
    Serial.println(" background scan cycles; continuing RC-only and retrying later");
    reconnectAttemptCount = 0;
  } else {
    Serial.print("WiFi scan cycle failed (");
    Serial.print(reconnectAttemptCount);
    Serial.print("/");
    Serial.print(MAX_RECONNECT_ATTEMPTS);
    Serial.println("); RC remains active");
  }
}

// Check WiFi status and advance the non-blocking background connection state
bool checkWiFiStatus() {
  unsigned long now = millis();

  if (now - lastWifiCheckMs < WIFI_CHECK_INTERVAL_MS) {
    return cachedWifiConnected;
  }
  lastWifiCheckMs = now;

  bool wifiConnected = (WiFi.status() == WL_CONNECTED);
  cachedWifiConnected = wifiConnected;

  if (wifiConnected) {
    bool hadPreviousWifiSession = currentNetworkIndex >= 0;
    if (wifiAttemptActive && isWifiNetworkConfigured(wifiAttemptNetworkIndex)) {
      currentNetworkIndex = wifiAttemptNetworkIndex;
    }

    if (wifiConnectedAtMs == 0) {
      wifiConnectedAtMs = now;
    }

    if (lastWifiDisconnectMs > 0 || !udpServersStarted) {
      printWifiConnectedInfo(currentNetworkIndex);
      if (lastWifiDisconnectMs > 0 && hadPreviousWifiSession) {
        Serial.println("WiFi link restored");
      }
    }

    lastWifiDisconnectMs = 0;
    reconnectAttemptCount = 0;
    reconnectInProgress = false;
    resetWifiAttemptState();
    ensureUdpServersStarted(now, wifiConnected);
    return true;
  }

  stopUdpServers();
  wifiConnectedAtMs = 0;
  lastUdpStartAttemptMs = 0;

  if (lastWifiDisconnectMs == 0) {
    lastWifiDisconnectMs = now;
    Serial.println("\nWiFi not connected - RC remains active while background connect runs");
  }

  if (wifiAttemptActive) {
    if (now - wifiAttemptStartMs >= WIFI_CONNECT_ATTEMPT_TIMEOUT_MS) {
      Serial.print("WiFi attempt timed out: ");
      Serial.println(wifiNetworks[wifiAttemptNetworkIndex].ssid);
      WiFi.disconnect();
      wifiAttemptActive = false;
      wifiAttemptStartMs = 0;
      wifiNetworksTriedThisCycle++;

      if (!startNextWifiAttempt(now)) {
        finishWifiReconnectCycle(now);
      }
    }
    return false;
  }

  if (!reconnectInProgress) {
    if (now - lastWifiDisconnectMs < WIFI_RECONNECT_DELAY_MS) {
      return false;
    }
    beginWifiReconnectCycle(now, false);
  }

  if (!startNextWifiAttempt(now)) {
    finishWifiReconnectCycle(now);
  }
  return false;
}

// === Setup ===

void setup() {
  // Drive the ESC pins to a valid neutral pulse immediately on boot.
  // Hardware PWM keeps running even if another library briefly disables interrupts.
  currentLeftUs = ESC_MID;
  currentRightUs = ESC_MID;
  wifiAvgL = ESC_MID;
  wifiAvgR = ESC_MID;
  wifiOutL = ESC_MID;
  wifiOutR = ESC_MID;
  rcAvgL = ESC_MID;
  rcAvgR = ESC_MID;
  rcOutL = ESC_MID;
  rcOutR = ESC_MID;
  initEscPwmOutputs();
  delay(50);

  // Initialize Serial
  Serial.begin(115200);
  delay(200);

  Serial.println("\n=== WiFi UDP + RC Thruster Control + Flow Meter + DHT22 ===");
  Serial.print("RC Control Mode: ");
  Serial.println(ENABLE_GEAR_MODE ? "Gear Mode (9 gears, 100µs intervals)" : "Continuous Mode");
  Serial.print("ESC Output: ");
  Serial.println(escPwmInitialized ? "Hardware PWM (PwmOut)" : "Hardware PWM init FAILED");
  Serial.println();

  // Configure RC input pins
  // RC PWM idles low and pulses high, so pulldown is the safest default when the receiver is off.
  pinMode(CH_RIGHT_IN, INPUT_PULLDOWN);
  pinMode(CH_LEFT_IN, INPUT_PULLDOWN);
  Serial.println("RC input pins configured");

  // Attach interrupts for PWM capture
  attachInterrupt(digitalPinToInterrupt(CH_RIGHT_IN), onRightChange, CHANGE);
  attachInterrupt(digitalPinToInterrupt(CH_LEFT_IN), onLeftChange, CHANGE);
  Serial.println("RC interrupts attached");

  // Configure flow meter pin
  pinMode(FLOW_SENSOR_PIN, INPUT_PULLUP);
  lastFlowState = digitalRead(FLOW_SENSOR_PIN);
  Serial.println("Flow meter sensor configured on D7");

  ledMatrixInitialized = ledMatrix.begin();
  if (ledMatrixInitialized) {
    renderWifiStatusMatrix(false);
    Serial.println("LED Matrix WiFi indicator initialized");
  } else {
    Serial.println("LED Matrix init FAILED");
  }

  // Initialize DHT sensors
  if (ENABLE_DHT_SENSORS) {
    dht1.begin();
    dht2.begin();
    Serial.println("DHT22 sensors configured on D12 and D13");
  } else {
    Serial.println("DHT22 sensors disabled to avoid interrupt-related ESC twitching");
  }

  // Keep neutral stable for ESC arming before any long-running init such as WiFi scans.
  Serial.print("ESCs initialized to neutral (1500 us), holding for ");
  Serial.print(ESC_SAFE_BOOT_NEUTRAL_MS);
  Serial.println(" ms");
  delay(ESC_SAFE_BOOT_NEUTRAL_MS);

  // Start WiFi in the background so RC is usable immediately after setup finishes.
  int configuredWifiCount = countConfiguredWifiNetworks();
  if (configuredWifiCount > 0) {
    Serial.println("WiFi background connect enabled - RC available immediately");
    lastWifiDisconnectMs = millis();
    beginWifiReconnectCycle(millis(), true);
  } else {
    Serial.println("No WiFi networks configured - Running in RC only mode");
  }

  Serial.println("\n=== System Ready ===");
  Serial.println("Control Priority: UDP > RC > Failsafe");
  Serial.println("Flow Meter: D7 polling mode, 1 Hz update rate");
  if (ENABLE_DHT_SENSORS) {
    Serial.println("DHT22: D12 and D13, 1 Hz update rate");
  } else {
    Serial.println("DHT22: DISABLED");
  }
  Serial.println("UDP: Listen 8888, Send S/F/D to 192.168.50.200:28888");
  Serial.println("     S/F/D also sent to 192.168.50.200:28889 (monitor)");
  Serial.println("     HEARTBEAT broadcast to 192.168.50.255:8889");
  Serial.println("     HEARTBEAT unicast to 192.168.50.200:28887 (Jetson)");
  Serial.println();
}

// === Main Loop ===

void loop() {
  unsigned long now = millis();

  // 0. Poll flow sensor (lightweight, high frequency)
  pollFlowSensor();

  // 1. Read RC inputs first so manual control stays responsive even during WiFi retries
  readRcInputs();

  // 2. Check WiFi status and auto-reconnect in the background
  bool wifiConnected = checkWiFiStatus();

  // 3. Poll again after WiFi check (may have missed pulses)
  pollFlowSensor();

  // 4. Read UDP commands and heartbeat only after sockets are ready
  if (udpServersStarted) {
    readUdpCommands();
    readHeartbeatPing();
  }

  // 5. Poll again after UDP read (critical - UDP can block)
  pollFlowSensor();

  // 6. Determine control mode and outputs (fast)
  determineControlMode();

  // 7. Update thrusters (fast)
  updateThrusters();

  // 7.5. Dedicated PWM debug stream for investigating twitching
  printPwmEventDebug();
  printPwmDebug(now);

  // 7.6. LED Matrix WiFi status indicator
  updateWifiStatusMatrix(now, wifiConnected);

  // 8. Refresh DHT cache before any optional telemetry send
  readDhtSensor(now);

  // 9. Allow at most one outbound UDP task per loop, after control outputs are updated
  serviceOneUdpSendTask(now, wifiConnected);

  // 10. Final poll before loop restart
  pollFlowSensor();

  // 11. Calculate flow data (do this once per loop)
  calculateFlowData(now);

  // 12. Connection state transitions (fast)
  bool wifiLink = wifiConnected;
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

  // Debug output (configurable level)
  static unsigned long lastDebugMs = 0;
  if (now - lastDebugMs >= 1000) {  // Print every 1 second
    lastDebugMs = now;

    // DEBUG_LEVEL 0: No periodic output
    // DEBUG_LEVEL 1: Basic status + sensors
    // DEBUG_LEVEL 2: Verbose (all info)

    if (DEBUG_LEVEL >= 1) {
      // Basic: Mode and WiFi status
      Serial.print("[");
      Serial.print(currentMode == 1 ? "WiFi" : "RC");
      Serial.print("] ");

      // WiFi cmd age
      if (currentMode == 1) {
        unsigned long cmdAge = haveWifiCmd ? (now - lastWifiCmdMs) : 0;
        Serial.print("cmd:");
        Serial.print(cmdAge);
        Serial.print("ms ");
      }

      // Flow data
      Serial.print("| Flow:");
      Serial.print(flowLmin, 2);
      Serial.print("L/min ");
      Serial.print(flowVelocity, 3);
      Serial.print("m/s ");
      Serial.print(totalLiters, 2);
      Serial.print("L ");

      // DHT data
      if (ENABLE_DHT_SENSORS) {
        Serial.print("| DHT1:");
        Serial.print(dht1Temperature, 1);
        Serial.print("C ");
        Serial.print(dht1Humidity, 0);
        Serial.print("% ");
        Serial.print("DHT2:");
        Serial.print(dht2Temperature, 1);
        Serial.print("C ");
        Serial.print(dht2Humidity, 0);
        Serial.print("%");
      } else {
        Serial.print("| DHT:OFF");
      }

      Serial.println();
    }

    if (DEBUG_LEVEL >= 2) {
      // Verbose: Additional details
      Serial.print("  [VERBOSE] ESC L:");
      Serial.print(currentLeftUs);
      Serial.print(" R:");
      Serial.print(currentRightUs);
      Serial.print(" | Jetson:");
      Serial.print(isJetsonOnline(now) ? "ON" : "OFF");
      Serial.print(" | Monitor sent:");
      Serial.println(now - lastMonitorSendMs < 1100 ? "OK" : "SKIP");
    }
  }
}
