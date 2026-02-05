#include <rclcpp/rclcpp.hpp>
#include "thruster_control/msg/thruster_cmd_pwm.hpp"
#include "thruster_control/msg/thruster_status_pwm.hpp"
#include "thruster_control/msg/speed_data.hpp"
#include "thruster_control/msg/connection_status.hpp"
#include "thruster_control/msg/thruster_metrics.hpp"

#include <algorithm>
#include <arpa/inet.h>
#include <cerrno>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cctype>
#include <cstring>
#include <fcntl.h>
#include <fstream>
#include <iomanip>
#include <memory>
#include <netdb.h>
#include <netinet/in.h>
#include <sys/socket.h>
#include <unistd.h>
#include <vector>
#include <sstream>
#include <string>

namespace thruster_control
{

class UdpClient
{
public:
  UdpClient() = default;
  ~UdpClient() { close(); }

  // Three-port architecture:
  // - Send commands to Arduino:8888 (C <left> <right>)
  // - Send PING to Arduino:8889, receive broadcast heartbeat on local 8889
  // - Receive unicast data (S/F) on local data_port (28888)
  bool bind(const std::string & arduino_host, int arduino_cmd_port, int arduino_ping_port,
            int data_port, int heartbeat_port)
  {
    close();
    last_error_.clear();

    // Store port numbers
    arduino_cmd_port_ = arduino_cmd_port;
    arduino_ping_port_ = arduino_ping_port;
    data_port_ = data_port;
    heartbeat_port_ = heartbeat_port;

    // Resolve Arduino address for sending commands (port 8888)
    struct addrinfo hints;
    std::memset(&hints, 0, sizeof(hints));
    hints.ai_family = AF_UNSPEC;
    hints.ai_socktype = SOCK_DGRAM;

    struct addrinfo * result = nullptr;
    const std::string cmd_port_str = std::to_string(arduino_cmd_port);
    int rc = ::getaddrinfo(arduino_host.c_str(), cmd_port_str.c_str(), &hints, &result);
    if (rc != 0) {
      last_error_ = ::gai_strerror(rc);
      return false;
    }
    std::memcpy(&arduino_cmd_addr_, result->ai_addr, result->ai_addrlen);
    arduino_cmd_addrlen_ = result->ai_addrlen;
    ::freeaddrinfo(result);

    // Resolve Arduino address for sending PING (port 8889)
    result = nullptr;
    const std::string ping_port_str = std::to_string(arduino_ping_port);
    rc = ::getaddrinfo(arduino_host.c_str(), ping_port_str.c_str(), &hints, &result);
    if (rc != 0) {
      last_error_ = ::gai_strerror(rc);
      return false;
    }
    std::memcpy(&arduino_ping_addr_, result->ai_addr, result->ai_addrlen);
    arduino_ping_addrlen_ = result->ai_addrlen;
    ::freeaddrinfo(result);

    // Create data socket and bind to data port (receives S, F messages)
    data_sock_ = createSocket(data_port);
    if (data_sock_ < 0) {
      return false;
    }

    // Create heartbeat socket and bind to heartbeat port (receives unicast HEARTBEAT)
    heartbeat_sock_ = createSocket(heartbeat_port);
    if (heartbeat_sock_ < 0) {
      close();
      last_error_ = "Failed to bind heartbeat socket";
      return false;
    }

    // Create PING socket, bind to local port 8889 to receive broadcast heartbeat
    // Also used to send PING to Arduino:8889
    ping_sock_ = createSocket(arduino_ping_port);
    if (ping_sock_ < 0) {
      close();
      last_error_ = "Failed to bind ping socket";
      return false;
    }

    buffer_.clear();
    return true;
  }

  void close()
  {
    if (data_sock_ >= 0) {
      ::close(data_sock_);
      data_sock_ = -1;
    }
    if (heartbeat_sock_ >= 0) {
      ::close(heartbeat_sock_);
      heartbeat_sock_ = -1;
    }
    if (ping_sock_ >= 0) {
      ::close(ping_sock_);
      ping_sock_ = -1;
    }
    buffer_.clear();
  }

  bool isConnected() const { return data_sock_ >= 0 && heartbeat_sock_ >= 0 && ping_sock_ >= 0; }

  const std::string & lastError() const { return last_error_; }
  int getDataPort() const { return data_port_; }
  int getHeartbeatPort() const { return heartbeat_port_; }
  int getPingPort() const { return arduino_ping_port_; }

  // Send command to Arduino (port 8888)
  bool sendCommand(const std::string & line)
  {
    if (data_sock_ < 0) {
      last_error_ = "socket closed";
      return false;
    }

    std::string payload = line;
    if (payload.empty() || payload.back() != '\n') {
      payload.push_back('\n');
    }

    ssize_t sent = ::sendto(data_sock_, payload.data(), payload.size(), 0,
                            reinterpret_cast<const struct sockaddr *>(&arduino_cmd_addr_), arduino_cmd_addrlen_);

    if (sent < 0) {
      last_error_ = std::strerror(errno);
      return false;
    }
    if (static_cast<size_t>(sent) != payload.size()) {
      last_error_ = "partial send";
      return false;
    }

    return true;
  }

  // Send PING to Arduino (port 8889)
  bool sendPing()
  {
    if (ping_sock_ < 0) {
      last_error_ = "ping socket closed";
      return false;
    }

    const std::string payload = "PING\n";

    ssize_t sent = ::sendto(ping_sock_, payload.data(), payload.size(), 0,
                            reinterpret_cast<const struct sockaddr *>(&arduino_ping_addr_), arduino_ping_addrlen_);

    if (sent < 0) {
      last_error_ = std::strerror(errno);
      return false;
    }
    if (static_cast<size_t>(sent) != payload.size()) {
      last_error_ = "partial send";
      return false;
    }

    return true;
  }

  // Read from all three sockets (data, heartbeat, ping)
  bool readLines(std::vector<std::string> & lines)
  {
    bool read_any = false;
    read_any |= readFromSocket(data_sock_, buffer_, lines);
    read_any |= readFromSocket(heartbeat_sock_, buffer_, lines);
    read_any |= readFromSocket(ping_sock_, buffer_, lines);
    return read_any;
  }

private:
  bool readFromSocket(int sock, std::string & buffer, std::vector<std::string> & lines)
  {
    if (sock < 0) {
      return false;
    }

    bool read_any = false;
    char buf[256];
    ssize_t n = ::recv(sock, buf, sizeof(buf), MSG_DONTWAIT);
    if (n > 0) {
      read_any = true;
      buffer.append(buf, static_cast<size_t>(n));
      std::string line;
      while (extractLine(buffer, line)) {
        lines.emplace_back(std::move(line));
      }
    } else if (n < 0) {
      if (errno != EAGAIN && errno != EWOULDBLOCK && errno != EINTR) {
        last_error_ = std::strerror(errno);
      }
    }

    return read_any;
  }

  int createSocket(int port)
  {
    int fd = ::socket(AF_INET, SOCK_DGRAM, 0);
    if (fd < 0) {
      last_error_ = std::strerror(errno);
      return -1;
    }

    // Set non-blocking
    int flags = ::fcntl(fd, F_GETFL, 0);
    if (flags < 0 || ::fcntl(fd, F_SETFL, flags | O_NONBLOCK) < 0) {
      last_error_ = std::strerror(errno);
      ::close(fd);
      return -1;
    }

    // Allow address reuse
    int opt = 1;
    if (::setsockopt(fd, SOL_SOCKET, SO_REUSEADDR, &opt, sizeof(opt)) < 0) {
      last_error_ = std::strerror(errno);
      ::close(fd);
      return -1;
    }

    // Bind to port
    struct sockaddr_in addr;
    std::memset(&addr, 0, sizeof(addr));
    addr.sin_family = AF_INET;
    addr.sin_addr.s_addr = INADDR_ANY;
    addr.sin_port = htons(port);

    if (::bind(fd, reinterpret_cast<struct sockaddr *>(&addr), sizeof(addr)) < 0) {
      last_error_ = std::strerror(errno);
      ::close(fd);
      return -1;
    }

    return fd;
  }

  bool extractLine(std::string & buffer, std::string & line)
  {
    // Prevent buffer overflow
    if (buffer.size() > 65536) {
      last_error_ = "buffer overflow - no newline found";
      buffer.clear();
      return false;
    }

    auto pos = buffer.find('\n');
    if (pos == std::string::npos) {
      return false;
    }
    line = buffer.substr(0, pos);
    buffer.erase(0, pos + 1);
    if (!line.empty() && line.back() == '\r') {
      line.pop_back();
    }
    return true;
  }

  int data_sock_{-1};
  int heartbeat_sock_{-1};
  int ping_sock_{-1};
  int data_port_{0};
  int heartbeat_port_{0};
  int arduino_cmd_port_{0};
  int arduino_ping_port_{0};
  std::string buffer_;
  std::string last_error_;

  // Arduino command address (port 8888)
  struct sockaddr_storage arduino_cmd_addr_;
  socklen_t arduino_cmd_addrlen_{0};

  // Arduino PING address (port 8889)
  struct sockaddr_storage arduino_ping_addr_;
  socklen_t arduino_ping_addrlen_{0};
};

class ThrusterWifiNode : public rclcpp::Node
{
public:
  ThrusterWifiNode()
  : rclcpp::Node("thruster_wifi_node"),
    consecutive_failures_(0),
    reconnect_count_(0),
    avg_loop_time_ms_(0.0)
  {
    // Network parameters
    host_ = declare_parameter<std::string>("host", "192.168.50.100");
    arduino_cmd_port_ = declare_parameter<int>("arduino_cmd_port", 8888);   // Arduino command port (C <left> <right>)
    arduino_ping_port_ = declare_parameter<int>("arduino_ping_port", 8889); // Arduino PING port (PING/heartbeat)
    data_port_ = declare_parameter<int>("data_port", 28888);               // Local data port (receives S, F)
    heartbeat_port_ = declare_parameter<int>("heartbeat_port", 28887);     // Local heartbeat port
    udp_timeout_ = declare_parameter<double>("udp_timeout", 5.0);
    read_period_ = std::chrono::duration<double>(declare_parameter<double>("read_interval", 0.05));
    reconnect_delay_ = std::chrono::duration<double>(declare_parameter<double>("reconnect_delay", 2.0));
    max_reconnect_delay_ = std::chrono::duration<double>(declare_parameter<double>("max_reconnect_delay", 60.0));
    stop_command_ = declare_parameter<std::string>("stop_cmd", "C 1500 1500");
    status_frame_id_ = declare_parameter<std::string>("status_frame_id", "thruster_link");

    // Logging parameters
    log_level_ = declare_parameter<std::string>("log_level", "INFO");
    log_heartbeat_ = declare_parameter<bool>("enable_heartbeat_log", true);
    log_command_ = declare_parameter<bool>("enable_command_log", true);
    log_status_ = declare_parameter<bool>("enable_status_log", false);
    log_speed_ = declare_parameter<bool>("enable_speed_log", false);
    log_to_file_ = declare_parameter<bool>("log_to_file", false);
    log_file_path_ = declare_parameter<std::string>("log_file_path", "/tmp/thruster_wifi.log");
    int max_size_mb = declare_parameter<int>("max_log_file_size_mb", 10);
    max_log_size_ = static_cast<size_t>(max_size_mb) * 1024 * 1024;

    // Metrics parameters
    metrics_publish_rate_ = declare_parameter<double>("metrics_publish_rate", 1.0);

    // Initialize file logging if enabled
    if (log_to_file_) {
      initFileLogging();
    }

    // Publishers
    status_pub_ = create_publisher<thruster_control::msg::ThrusterStatusPWM>("thruster_status_pwm", 10);
    speed_pub_ = create_publisher<thruster_control::msg::SpeedData>("speed_data", 10);
    connection_pub_ = create_publisher<thruster_control::msg::ConnectionStatus>("thruster_connection_status", 10);
    metrics_pub_ = create_publisher<thruster_control::msg::ThrusterMetrics>("thruster_metrics", 10);

    // Subscriber
    command_sub_ = create_subscription<thruster_control::msg::ThrusterCmdPWM>(
      "thruster_cmd_pwm", 10,
      std::bind(&ThrusterWifiNode::handleCommand, this, std::placeholders::_1));

    // Timer
    timer_ = create_wall_timer(read_period_, std::bind(&ThrusterWifiNode::onTimer, this));

    // PING timer (1Hz)
    ping_timer_ = create_wall_timer(std::chrono::seconds(1), std::bind(&ThrusterWifiNode::onPingTimer, this));

    // Initialize timing
    next_reconnect_time_ = std::chrono::steady_clock::now();
    last_udp_receive_ = std::chrono::steady_clock::time_point();
    last_metrics_pub_ = std::chrono::steady_clock::now();
    loop_start_ = std::chrono::steady_clock::now();
    stats_.stats_start = std::chrono::steady_clock::now();

    logInfo("Thruster WiFi Node initialized");
    logInfo("Arduino command: " + host_ + ":" + std::to_string(arduino_cmd_port_));
    logInfo("Arduino PING: " + host_ + ":" + std::to_string(arduino_ping_port_) + " (local port: " + std::to_string(arduino_ping_port_) + ")");
    logInfo("Local data port: " + std::to_string(data_port_) + ", heartbeat port: " + std::to_string(heartbeat_port_));
    logInfo("Log level: " + log_level_);
  }

  ~ThrusterWifiNode() override
  {
    if (client_.isConnected() && !stop_command_.empty()) {
      if (client_.sendCommand(stop_command_)) {
        logInfo("Sent stop command on shutdown: " + stop_command_);
      } else {
        logWarn("Failed to send stop command on shutdown");
      }
    }
    client_.close();

    // Close log file
    if (log_file_.is_open()) {
      log_file_.close();
    }
  }

private:
  // === Logging Methods ===

  void writeToFile(const std::string & level, const std::string & msg)
  {
    if (!log_file_.is_open()) {
      return;
    }

    // Check file size
    if (log_file_.tellp() > 0 && static_cast<size_t>(log_file_.tellp()) > max_log_size_) {
      // Rotate log file
      log_file_.close();
      std::string old_path = log_file_path_ + ".old";
      std::rename(log_file_path_.c_str(), old_path.c_str());
      log_file_.open(log_file_path_, std::ios::app);
    }

    // Write timestamped log entry
    auto now = std::chrono::system_clock::now();
    auto time_t = std::chrono::system_clock::to_time_t(now);
    auto ms = std::chrono::duration_cast<std::chrono::milliseconds>(
      now.time_since_epoch()) % 1000;

    log_file_ << std::put_time(std::localtime(&time_t), "%Y-%m-%d %H:%M:%S")
              << '.' << std::setfill('0') << std::setw(3) << ms.count()
              << " [" << level << "] " << msg << std::endl;
    log_file_.flush();
  }

  void initFileLogging()
  {
    log_file_.open(log_file_path_, std::ios::app);
    if (!log_file_.is_open()) {
      RCLCPP_WARN(get_logger(), "Failed to open log file: %s", log_file_path_.c_str());
      log_to_file_ = false;
    } else {
      writeToFile("INFO", "=== Thruster WiFi Node Started ===");
    }
  }

  size_t levelIndex(const std::string & level) const
  {
    static const std::vector<std::string> levels = {"DEBUG", "INFO", "WARN", "ERROR"};
    auto it = std::find(levels.begin(), levels.end(), level);
    return (it != levels.end()) ? static_cast<size_t>(it - levels.begin()) : 1;
  }

  bool shouldLog(const std::string & level) const
  {
    size_t current_idx = levelIndex(log_level_);
    size_t msg_idx = levelIndex(level);
    return msg_idx >= current_idx;
  }

  void logWithLevel(const std::string & level, const std::string & msg)
  {
    if (!shouldLog(level)) {
      return;
    }

    // Console logging via RCLCPP
    if (level == "DEBUG") {
      RCLCPP_DEBUG(get_logger(), "%s", msg.c_str());
    } else if (level == "INFO") {
      RCLCPP_INFO(get_logger(), "%s", msg.c_str());
    } else if (level == "WARN") {
      RCLCPP_WARN(get_logger(), "%s", msg.c_str());
    } else if (level == "ERROR") {
      RCLCPP_ERROR(get_logger(), "%s", msg.c_str());
    }

    // File logging
    if (log_to_file_) {
      writeToFile(level, msg);
    }
  }

  void logDebug(const std::string & msg) { logWithLevel("DEBUG", msg); }
  void logInfo(const std::string & msg) { logWithLevel("INFO", msg); }
  void logWarn(const std::string & msg) { logWithLevel("WARN", msg); }
  void logError(const std::string & msg) { logWithLevel("ERROR", msg); }

  // === Main Loop ===

  void onTimer()
  {
    const auto now = std::chrono::steady_clock::now();

    // Measure loop time
    auto loop_time = now - loop_start_;
    double loop_ms = std::chrono::duration<double, std::milli>(loop_time).count();
    avg_loop_time_ms_ = avg_loop_time_ms_ * 0.9 + loop_ms * 0.1;  // Exponential moving average
    loop_start_ = now;

    // Check Arduino online status via timeout
    auto timeout_duration = std::chrono::duration_cast<std::chrono::steady_clock::duration>(
      std::chrono::duration<double>(udp_timeout_));
    bool was_online = arduino_online_;
    arduino_online_ = (now - last_udp_receive_) < timeout_duration;

    if (was_online && !arduino_online_) {
      logWarn("Arduino offline (no data for " + std::to_string(udp_timeout_) + "s)");
      stats_.timeouts++;
      publishConnectionStatus();
    } else if (!was_online && arduino_online_) {
      logInfo("Arduino online");
      publishConnectionStatus();
    }

    if (!client_.isConnected()) {
      if (now >= next_reconnect_time_) {
        attemptConnect();
      }
      return;
    }

    // Read data from socket (status, speed, heartbeat)
    pollSocket();

    // Publish metrics periodically
    publishMetrics();
  }

  void attemptConnect()
  {
    auto current_delay = reconnect_delay_ * std::pow(2.0, std::min(consecutive_failures_, 5));
    if (current_delay > max_reconnect_delay_) {
      current_delay = max_reconnect_delay_;
    }

    double delay_sec = std::chrono::duration<double>(current_delay).count();
    logDebug("Attempting reconnect (failures: " + std::to_string(consecutive_failures_) +
             ", delay: " + std::to_string(delay_sec) + "s)");

    next_reconnect_time_ = std::chrono::steady_clock::now() +
      std::chrono::duration_cast<std::chrono::steady_clock::duration>(current_delay);

    if (client_.bind(host_, arduino_cmd_port_, arduino_ping_port_, data_port_, heartbeat_port_)) {
      logInfo("UDP sockets bound - data:" + std::to_string(data_port_) +
              ", heartbeat:" + std::to_string(heartbeat_port_) +
              ", ping:" + std::to_string(arduino_ping_port_) +
              " for Arduino at " + host_ + ":" + std::to_string(arduino_cmd_port_));
      consecutive_failures_ = 0;
      reconnect_count_++;

      // Reset stats on reconnect
      stats_.reset();
      last_sent_valid_ = false;
      last_command_was_stop_ = false;
      arduino_online_ = false;
      // Note: last_udp_receive_ NOT set here - only update when actual data is received
      logInfo("State tracking reset after reconnect");

      // Publish connection status
      publishConnectionStatus();
    } else {
      consecutive_failures_++;
      logError("UDP bind failed (attempt " + std::to_string(consecutive_failures_) +
               ", next retry in " + std::to_string(delay_sec) + "s): " +
               client_.lastError());
    }
  }

  void handleCommand(const thruster_control::msg::ThrusterCmdPWM::SharedPtr msg)
  {
    if (!client_.isConnected()) {
      logWarn("UDP not bound; command dropped");
      return;
    }

    const bool is_stop_command = (msg->left_pwm == 1500 && msg->right_pwm == 1500);
    const auto now = std::chrono::steady_clock::now();

    // Check if thruster is already in stop state
    if (is_stop_command && last_sent_valid_ &&
        last_sent_left_pwm_ == 1500 && last_sent_right_pwm_ == 1500) {
      logDebug("Thruster already in stop state, command suppressed");
      return;
    }

    // Check if we've been sending stop commands for more than 3 seconds
    if (is_stop_command && last_command_was_stop_) {
      if (now - last_stop_command_time_ >= stop_command_suppression_) {
        logDebug("Stop command suppressed (continuous stop > 3s)");
        return;
      }
    }

    const std::string payload = formatCommand(msg->left_pwm, msg->right_pwm);
    if (!client_.sendCommand(payload)) {
      logError("Failed to send command: " + std::string(client_.lastError()));

      last_sent_valid_ = false;
      last_command_was_stop_ = false;
      logWarn("State tracking invalidated due to send failure");

      next_reconnect_time_ = now;
      return;
    }

    stats_.tx_packets++;
    if (log_command_) {
      logInfo("TX PWM: " + payload);
    }

    // Only update tracking after successful send
    last_sent_left_pwm_ = msg->left_pwm;
    last_sent_right_pwm_ = msg->right_pwm;
    last_sent_valid_ = true;

    // Update stop command tracking
    if (is_stop_command) {
      last_stop_command_time_ = now;
      last_command_was_stop_ = true;
    } else {
      last_command_was_stop_ = false;
    }
  }

  void pollSocket()
  {
    std::vector<std::string> lines;
    const auto now = std::chrono::steady_clock::now();

    // Read from all sockets (data: S status, F flow, HEARTBEAT from ping_sock)
    if (client_.readLines(lines)) {
      // Update last receive time if any data was received
      last_udp_receive_ = now;
    }

    for (auto & line : lines) {
      stats_.rx_packets++;

      // Check for status message: S <mode> <left_pwm> <right_pwm>
      if (!line.empty() && line[0] == 'S') {
        auto parsed = parseStatus(line);
        if (parsed.has_value()) {
          thruster_control::msg::ThrusterStatusPWM msg;
          msg.header.stamp = this->get_clock()->now();
          msg.header.frame_id = status_frame_id_;
          msg.mode = parsed->mode;
          msg.left_pwm = parsed->left_pwm;
          msg.right_pwm = parsed->right_pwm;
          status_pub_->publish(msg);
          stats_.rx_status++;
          if (log_status_) {
            logDebug("RX Status: " + line);
          }
        } else {
          stats_.parse_errors++;
          if (log_status_) {
            logDebug("Failed to parse status: " + line);
          }
        }
      }
      // Check for speed data message: F <freq_hz> <flow_lmin> <velocity_ms> <total_liters>
      else if (!line.empty() && line[0] == 'F') {
        auto parsed = parseSpeedData(line);
        if (parsed.has_value()) {
          thruster_control::msg::SpeedData msg;
          msg.header.stamp = this->get_clock()->now();
          msg.header.frame_id = status_frame_id_;
          msg.freq_hz = parsed->freq_hz;
          msg.flow_lmin = parsed->flow_lmin;
          msg.velocity_ms = parsed->velocity_ms;
          msg.total_liters = parsed->total_liters;
          speed_pub_->publish(msg);
          stats_.rx_speed++;
          if (log_speed_) {
            logDebug("RX Speed: " + line);
          }
        } else {
          stats_.parse_errors++;
          if (log_speed_) {
            logDebug("Failed to parse speed data: " + line);
          }
        }
      }
      // Check for heartbeat (from broadcast on port 8889 or unicast)
      else if (line == "HEARTBEAT") {
        stats_.rx_heartbeat++;
        if (log_heartbeat_) {
          logDebug("RX HEARTBEAT");
        }
      } else {
        stats_.parse_errors++;
        logDebug("Unknown message: " + line);
      }
    }
  }

  void onPingTimer()
  {
    if (!client_.isConnected()) {
      return;
    }

    if (client_.sendPing()) {
      stats_.tx_ping++;
      if (log_command_) {
        logDebug("TX PING");
      }
    } else {
      logError("Failed to send PING: " + std::string(client_.lastError()));
    }
  }

  void publishConnectionStatus()
  {
    thruster_control::msg::ConnectionStatus msg;
    msg.header.stamp = this->get_clock()->now();
    msg.wifi_bound = client_.isConnected();
    msg.arduino_online = arduino_online_;
    msg.reconnect_count = reconnect_count_;
    msg.uptime_sec = stats_.uptimeSec();
    connection_pub_->publish(msg);
  }

  void publishMetrics()
  {
    const auto now = std::chrono::steady_clock::now();
    auto min_interval = std::chrono::duration<double>(1.0 / metrics_publish_rate_);
    if (now - last_metrics_pub_ < std::chrono::duration_cast<std::chrono::steady_clock::duration>(min_interval)) {
      return;
    }
    last_metrics_pub_ = now;

    thruster_control::msg::ThrusterMetrics msg;
    msg.header.stamp = this->get_clock()->now();
    msg.tx_packets = stats_.tx_packets;
    msg.rx_packets = stats_.rx_packets;
    msg.rx_heartbeat = stats_.rx_heartbeat;
    msg.rx_status = stats_.rx_status;
    msg.rx_speed = stats_.rx_speed;
    msg.parse_errors = stats_.parse_errors;
    msg.timeouts = stats_.timeouts;
    msg.latency_ms = 0.0;  // Latency measurement not available (PING/PONG removed)
    msg.loop_time_ms = avg_loop_time_ms_;

    // Calculate throughput
    double uptime = stats_.uptimeSec();
    msg.throughput_bps = (uptime > 0) ? (stats_.bytes_received * 8.0 / uptime) : 0.0;

    // Calculate error rate
    uint64_t total_rx = stats_.rx_packets;
    msg.error_rate = (total_rx > 0) ? (stats_.parse_errors * 100.0 / total_rx) : 0.0;

    metrics_pub_->publish(msg);
  }

  // === Data Structures ===

  struct StatusSample
  {
    uint8_t mode{0};
    int32_t left_pwm{0};
    int32_t right_pwm{0};
  };

  struct SpeedDataSample
  {
    double freq_hz{0.0};
    double flow_lmin{0.0};
    double velocity_ms{0.0};
    double total_liters{0.0};
  };

  struct Stats
  {
    uint64_t tx_packets{0};
    uint64_t tx_ping{0};
    uint64_t rx_packets{0};
    uint64_t rx_heartbeat{0};
    uint64_t rx_status{0};
    uint64_t rx_speed{0};
    uint64_t parse_errors{0};
    uint64_t timeouts{0};
    uint64_t bytes_received{0};
    std::chrono::steady_clock::time_point stats_start;

    void reset()
    {
      tx_packets = tx_ping = rx_packets = rx_heartbeat = rx_status = rx_speed = 0;
      parse_errors = timeouts = 0;
      bytes_received = 0;
      stats_start = std::chrono::steady_clock::now();
    }

    double uptimeSec() const
    {
      auto now = std::chrono::steady_clock::now();
      return std::chrono::duration<double>(now - stats_start).count();
    }
  };

  // === Parser Methods ===

  static std::optional<StatusSample> parseStatus(const std::string & line)
  {
    std::vector<double> values;
    std::string current;
    for (char c : line) {
      if (std::isdigit(static_cast<unsigned char>(c)) || c == '.' || c == '-' || c == '+') {
        current.push_back(c);
      } else if (!current.empty()) {
        try {
          values.push_back(std::stod(current));
        } catch (const std::exception &) {
          return std::nullopt;
        }
        current.clear();
      }
    }
    if (!current.empty()) {
      try {
        values.push_back(std::stod(current));
      } catch (const std::exception &) {
        return std::nullopt;
      }
    }

    if (values.size() < 2) {
      return std::nullopt;
    }

    StatusSample sample;
    if (values.size() >= 3) {
      sample.mode = static_cast<uint8_t>(std::clamp(values[0], 0.0, 255.0));
      sample.left_pwm = static_cast<int32_t>(std::lround(values[1]));
      sample.right_pwm = static_cast<int32_t>(std::lround(values[2]));
    } else {
      sample.mode = 0;
      sample.left_pwm = static_cast<int32_t>(std::lround(values[0]));
      sample.right_pwm = static_cast<int32_t>(std::lround(values[1]));
    }
    return sample;
  }

  static std::optional<SpeedDataSample> parseSpeedData(const std::string & line)
  {
    std::vector<double> values;
    std::string current;
    for (char c : line) {
      if (std::isdigit(static_cast<unsigned char>(c)) || c == '.' || c == '-' || c == '+') {
        current.push_back(c);
      } else if (!current.empty()) {
        try {
          values.push_back(std::stod(current));
        } catch (const std::exception &) {
          return std::nullopt;
        }
        current.clear();
      }
    }
    if (!current.empty()) {
      try {
        values.push_back(std::stod(current));
      } catch (const std::exception &) {
        return std::nullopt;
      }
    }

    if (values.size() < 4) {
      return std::nullopt;
    }

    SpeedDataSample sample;
    sample.freq_hz = values[0];
    sample.flow_lmin = values[1];
    sample.velocity_ms = values[2];
    sample.total_liters = values[3];
    return sample;
  }

  static std::string formatCommand(int32_t left_pwm, int32_t right_pwm)
  {
    std::ostringstream oss;
    oss << "C " << left_pwm << ' ' << right_pwm;
    return oss.str();
  }

  // === Member Variables ===

  UdpClient client_;

  // Network configuration
  std::string host_;
  int arduino_cmd_port_{};
  int arduino_ping_port_{};
  int data_port_{};
  int heartbeat_port_{};
  double udp_timeout_{};
  std::chrono::duration<double> read_period_;
  std::chrono::duration<double> reconnect_delay_;
  std::chrono::duration<double> max_reconnect_delay_;
  std::string stop_command_;
  std::string status_frame_id_;

  // Logging configuration
  std::string log_level_;
  bool log_heartbeat_;
  bool log_command_;
  bool log_status_;
  bool log_speed_;
  bool log_to_file_;
  std::string log_file_path_;
  std::ofstream log_file_;
  size_t max_log_size_;

  // Metrics configuration
  double metrics_publish_rate_;

  // Publishers
  rclcpp::Publisher<thruster_control::msg::ThrusterStatusPWM>::SharedPtr status_pub_;
  rclcpp::Publisher<thruster_control::msg::SpeedData>::SharedPtr speed_pub_;
  rclcpp::Publisher<thruster_control::msg::ConnectionStatus>::SharedPtr connection_pub_;
  rclcpp::Publisher<thruster_control::msg::ThrusterMetrics>::SharedPtr metrics_pub_;

  // Subscriber
  rclcpp::Subscription<thruster_control::msg::ThrusterCmdPWM>::SharedPtr command_sub_;

  // Timer
  rclcpp::TimerBase::SharedPtr timer_;
  rclcpp::TimerBase::SharedPtr ping_timer_;

  // Timing state
  std::chrono::steady_clock::time_point next_reconnect_time_;
  std::chrono::steady_clock::time_point last_udp_receive_;
  std::chrono::steady_clock::time_point last_metrics_pub_;
  std::chrono::steady_clock::time_point loop_start_;

  // Connection state
  int consecutive_failures_;
  bool arduino_online_;
  uint32_t reconnect_count_;

  // Performance tracking
  double avg_loop_time_ms_;

  // Statistics
  Stats stats_;

  // Stop command optimization
  std::chrono::steady_clock::time_point last_stop_command_time_;
  bool last_command_was_stop_{false};
  const std::chrono::steady_clock::duration stop_command_suppression_{std::chrono::seconds(3)};

  // Track last sent PWM values
  int32_t last_sent_left_pwm_{0};
  int32_t last_sent_right_pwm_{0};
  bool last_sent_valid_{false};
};

}  // namespace thruster_control

int main(int argc, char ** argv)
{
  rclcpp::init(argc, argv);
  auto node = std::make_shared<thruster_control::ThrusterWifiNode>();
  rclcpp::spin(node);
  rclcpp::shutdown();
  return 0;
}
