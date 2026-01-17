#include <rclcpp/rclcpp.hpp>
#include "thruster_control/msg/thruster_cmd_pwm.hpp"
#include "thruster_control/msg/thruster_status_pwm.hpp"

#include <algorithm>
#include <arpa/inet.h>
#include <cerrno>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cctype>
#include <cstring>
#include <fcntl.h>
#include <memory>
#include <netdb.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <optional>
#include <poll.h>
#include <sstream>
#include <string>
#include <sys/socket.h>
#include <unistd.h>
#include <vector>

namespace thruster_control
{

class TcpClient
{
public:
  TcpClient() = default;
  ~TcpClient() { close(); }

  bool connect(const std::string & host, int port, double timeout_sec)
  {
    close();
    last_error_.clear();

    struct addrinfo hints;
    std::memset(&hints, 0, sizeof(hints));
    hints.ai_family = AF_UNSPEC;
    hints.ai_socktype = SOCK_STREAM;

    struct addrinfo * result = nullptr;
    const std::string port_str = std::to_string(port);
    int rc = ::getaddrinfo(host.c_str(), port_str.c_str(), &hints, &result);
    if (rc != 0) {
      last_error_ = ::gai_strerror(rc);
      return false;
    }

    const int timeout_ms = static_cast<int>(std::ceil(std::max(0.0, timeout_sec) * 1000.0));
    bool connected = false;

    for (auto * addr = result; addr != nullptr; addr = addr->ai_next) {
      int fd = ::socket(addr->ai_family, addr->ai_socktype, addr->ai_protocol);
      if (fd < 0) {
        continue;
      }

      int flags = ::fcntl(fd, F_GETFL, 0);
      if (flags < 0 || ::fcntl(fd, F_SETFL, flags | O_NONBLOCK) < 0) {
        ::close(fd);
        continue;
      }

      rc = ::connect(fd, addr->ai_addr, addr->ai_addrlen);
      if (rc == 0) {
        sock_ = fd;
        connected = true;
      } else if (errno == EINPROGRESS) {
        struct pollfd pfd;
        pfd.fd = fd;
        pfd.events = POLLOUT;
        rc = ::poll(&pfd, 1, timeout_ms);
        if (rc > 0 && (pfd.revents & POLLOUT)) {
          int err = 0;
          socklen_t err_len = sizeof(err);
          if (::getsockopt(fd, SOL_SOCKET, SO_ERROR, &err, &err_len) == 0 && err == 0) {
            sock_ = fd;
            connected = true;
          } else {
            last_error_ = std::strerror(err);
          }
        } else if (rc == 0) {
          last_error_ = "connect timeout";
        } else {
          last_error_ = std::strerror(errno);
        }
      } else {
        last_error_ = std::strerror(errno);
      }

      if (connected) {
        int one = 1;
        (void)::setsockopt(fd, IPPROTO_TCP, TCP_NODELAY, &one, sizeof(one));
        break;
      }

      ::close(fd);
    }

    ::freeaddrinfo(result);

    if (!connected) {
      if (last_error_.empty()) {
        last_error_ = "unable to connect";
      }
      return false;
    }

    buffer_.clear();
    return true;
  }

  void close()
  {
    if (sock_ >= 0) {
      ::close(sock_);
      sock_ = -1;
    }
    buffer_.clear();
  }

  bool isConnected() const { return sock_ >= 0; }

  const std::string & lastError() const { return last_error_; }

  bool sendLine(const std::string & line)
  {
    if (!isConnected()) {
      last_error_ = "socket closed";
      return false;
    }

    std::string payload = line;
    if (payload.empty() || payload.back() != '\n') {
      payload.push_back('\n');
    }

    const char * data = payload.data();
    size_t remaining = payload.size();
    while (remaining > 0) {
      ssize_t sent = ::send(
        sock_, data, remaining,
#ifdef MSG_NOSIGNAL
        MSG_NOSIGNAL
#else
        0
#endif
      );

      if (sent > 0) {
        remaining -= static_cast<size_t>(sent);
        data += sent;
        continue;
      }

      if (sent < 0) {
        if (errno == EINTR) {
          continue;
        }
        if (errno == EAGAIN || errno == EWOULDBLOCK) {
          if (!waitWritable(send_timeout_ms_)) {
            close();
            return false;
          }
          continue;
        }
        last_error_ = std::strerror(errno);
      } else {
        last_error_ = "send failed";
      }
      close();
      return false;
    }

    return true;
  }

  bool readLines(std::vector<std::string> & lines)
  {
    if (!isConnected()) {
      return false;
    }

    bool read_any = false;
    char buf[256];
    while (true) {
      ssize_t n = ::recv(sock_, buf, sizeof(buf), 0);
      if (n > 0) {
        read_any = true;
        buffer_.append(buf, static_cast<size_t>(n));
        std::string line;
        while (extractLine(line)) {
          lines.emplace_back(std::move(line));
        }
      } else if (n == 0) {
        last_error_ = "connection closed";
        close();
        break;
      } else {
        if (errno == EINTR) {
          continue;
        }
        if (errno == EAGAIN || errno == EWOULDBLOCK) {
          break;
        }
        last_error_ = std::strerror(errno);
        close();
        break;
      }
    }
    return read_any;
  }

  // Check if connection is still valid by attempting a non-blocking read
  // Returns false if connection is broken or closed
  bool checkConnection()
  {
    if (!isConnected()) {
      return false;
    }

    char buf[1];
    ssize_t n = ::recv(sock_, buf, sizeof(buf), MSG_PEEK | MSG_DONTWAIT);
    if (n > 0) {
      // Data available - connection is alive
      return true;
    } else if (n == 0) {
      // Connection closed by peer
      last_error_ = "connection closed by peer";
      close();
      return false;
    } else {
      if (errno == EAGAIN || errno == EWOULDBLOCK) {
        // No data available but connection is still valid
        return true;
      } else if (errno == EINTR) {
        // Interrupted - try again later
        return true;
      } else {
        // Error - connection broken
        last_error_ = std::strerror(errno);
        close();
        return false;
      }
    }
  }

private:
  bool waitWritable(int timeout_ms)
  {
    struct pollfd pfd;
    pfd.fd = sock_;
    pfd.events = POLLOUT;
    int rc = ::poll(&pfd, 1, timeout_ms);
    if (rc > 0 && (pfd.revents & POLLOUT)) {
      return true;
    }
    if (rc == 0) {
      last_error_ = "send timeout";
    } else {
      last_error_ = std::strerror(errno);
    }
    return false;
  }

  bool extractLine(std::string & line)
  {
    // Prevent buffer overflow: limit to 64KB
    if (buffer_.size() > 65536) {
      last_error_ = "buffer overflow - no newline found";
      buffer_.clear();
      return false;
    }

    auto pos = buffer_.find('\n');
    if (pos == std::string::npos) {
      return false;
    }
    line = buffer_.substr(0, pos);
    buffer_.erase(0, pos + 1);
    if (!line.empty() && line.back() == '\r') {
      line.pop_back();
    }
    return true;
  }

  int sock_{-1};
  std::string buffer_;
  std::string last_error_;
  const int send_timeout_ms_{1000};
};

class ThrusterWifiNode : public rclcpp::Node
{
public:
  ThrusterWifiNode()
  : rclcpp::Node("thruster_wifi_node"),
    consecutive_failures_(0)
  {
    host_ = declare_parameter<std::string>("host", "192.168.50.100");
    port_ = declare_parameter<int>("port", 8888);
    connect_timeout_ = declare_parameter<double>("connect_timeout", 5.0);
    read_period_ = std::chrono::duration<double>(declare_parameter<double>("read_interval", 0.05));
    reconnect_delay_ = std::chrono::duration<double>(declare_parameter<double>("reconnect_delay", 2.0));
    max_reconnect_delay_ = std::chrono::duration<double>(declare_parameter<double>("max_reconnect_delay", 60.0));
    heartbeat_interval_ = std::chrono::duration<double>(declare_parameter<double>("heartbeat_interval", 5.0));
    stop_command_ = declare_parameter<std::string>("stop_cmd", "C 1500 1500");
    status_frame_id_ = declare_parameter<std::string>("status_frame_id", "thruster_link");
    handshake_ = declare_parameter<std::string>("handshake", "HELLO");

    status_pub_ = create_publisher<thruster_control::msg::ThrusterStatusPWM>("thruster_status_pwm", 10);
    command_sub_ = create_subscription<thruster_control::msg::ThrusterCmdPWM>(
      "thruster_cmd_pwm", 10,
      std::bind(&ThrusterWifiNode::handleCommand, this, std::placeholders::_1));

    timer_ = create_wall_timer(read_period_, std::bind(&ThrusterWifiNode::onTimer, this));
    next_reconnect_time_ = std::chrono::steady_clock::now();
    last_heartbeat_check_ = std::chrono::steady_clock::now();
  }

  ~ThrusterWifiNode() override
  {
    if (client_.isConnected() && !stop_command_.empty()) {
      if (client_.sendLine(stop_command_)) {
        RCLCPP_INFO(get_logger(), "Sent stop command on shutdown: %s", stop_command_.c_str());
      } else {
        RCLCPP_WARN(get_logger(), "Failed to send stop command on shutdown");
      }
    }
    client_.close();
  }

private:
  void onTimer()
  {
    const auto now = std::chrono::steady_clock::now();
    if (!client_.isConnected()) {
      if (now >= next_reconnect_time_) {
        attemptConnect();
      }
      return;
    }

    // Perform periodic heartbeat check
    if (now - last_heartbeat_check_ >= 
        std::chrono::duration_cast<std::chrono::steady_clock::duration>(heartbeat_interval_)) {
      last_heartbeat_check_ = now;
      if (!client_.checkConnection()) {
        RCLCPP_WARN(get_logger(), "Heartbeat check failed: %s", client_.lastError().c_str());
        next_reconnect_time_ = now;  // Trigger immediate reconnect
        return;
      }
      RCLCPP_DEBUG(get_logger(), "Heartbeat check: connection healthy");
    }

    RCLCPP_DEBUG(get_logger(), "Polling socket for data");
    pollSocket();
  }

  void attemptConnect()
  {
    // Exponential backoff with max limit
    auto current_delay = reconnect_delay_ * std::pow(2.0, std::min(consecutive_failures_, 5));
    if (current_delay > max_reconnect_delay_) {
      current_delay = max_reconnect_delay_;
    }
    
    double delay_sec = std::chrono::duration<double>(current_delay).count();
    RCLCPP_DEBUG(get_logger(), "Attempting reconnect (failures: %d, delay: %.2fs)", 
                 consecutive_failures_, delay_sec);
    
    next_reconnect_time_ = std::chrono::steady_clock::now() + 
      std::chrono::duration_cast<std::chrono::steady_clock::duration>(current_delay);

    if (client_.connect(host_, port_, connect_timeout_)) {
      RCLCPP_INFO(get_logger(), "Connected to Arduino WiFi bridge at %s:%d", host_.c_str(), port_);
      consecutive_failures_ = 0;  // Reset on success

      // Reset tracking state on reconnect (Arduino may have rebooted)
      last_sent_valid_ = false;
      last_command_was_stop_ = false;
      RCLCPP_INFO(get_logger(), "State tracking reset after reconnect");

      if (!handshake_.empty()) {
        (void)client_.sendLine(handshake_);
      }
    } else {
      consecutive_failures_++;
      RCLCPP_WARN(get_logger(), "WiFi connect failed (attempt %d, next retry in %.2fs): %s", 
                  consecutive_failures_, delay_sec, client_.lastError().c_str());
    }
  }

  void handleCommand(const thruster_control::msg::ThrusterCmdPWM::SharedPtr msg)
  {
    if (!client_.isConnected()) {
      RCLCPP_WARN_THROTTLE(get_logger(), *get_clock(), 2000, "WiFi link not connected; command dropped");
      return;
    }

    const bool is_stop_command = (msg->left_pwm == 1500 && msg->right_pwm == 1500);
    const auto now = std::chrono::steady_clock::now();

    // Check if thruster is already in stop state
    if (is_stop_command && last_sent_valid_ &&
        last_sent_left_pwm_ == 1500 && last_sent_right_pwm_ == 1500) {
      RCLCPP_DEBUG(get_logger(), "Thruster already in stop state, command suppressed");
      return;
    }

    // Check if we've been sending stop commands for more than 3 seconds
    if (is_stop_command && last_command_was_stop_) {
      if (now - last_stop_command_time_ >= stop_command_suppression_) {
        RCLCPP_DEBUG(get_logger(), "Stop command suppressed (continuous stop > 3s)");
        return;
      }
    }

    const std::string payload = formatCommand(msg->left_pwm, msg->right_pwm);
    if (!client_.sendLine(payload)) {
      RCLCPP_ERROR(get_logger(), "Failed to send command: %s", client_.lastError().c_str());

      // Invalidate state on send failure - we don't know the actual state anymore
      last_sent_valid_ = false;
      last_command_was_stop_ = false;
      RCLCPP_WARN(get_logger(), "State tracking invalidated due to send failure");

      client_.close();
      // Trigger immediate reconnect on send failure
      next_reconnect_time_ = std::chrono::steady_clock::now();
      return;
    }
    RCLCPP_INFO(get_logger(), "TX PWM: %s", payload.c_str());

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
    client_.readLines(lines);
    for (auto & line : lines) {
      auto parsed = parseStatus(line);
      if (!parsed.has_value()) {
        RCLCPP_DEBUG(get_logger(), "Failed to parse line: %s", line.c_str());
        continue;
      }

      thruster_control::msg::ThrusterStatusPWM msg;
      msg.header.stamp = this->get_clock()->now();
      msg.header.frame_id = status_frame_id_;
      msg.mode = parsed->mode;
      msg.left_pwm = parsed->left_pwm;
      msg.right_pwm = parsed->right_pwm;
      status_pub_->publish(msg);
      RCLCPP_DEBUG(get_logger(), "RX PWM: %s", line.c_str());
    }

    if (!client_.isConnected()) {
      RCLCPP_WARN(get_logger(), "WiFi link lost: %s", client_.lastError().c_str());
      // Trigger immediate reconnect on connection loss
      next_reconnect_time_ = std::chrono::steady_clock::now();
    }
  }

  struct StatusSample
  {
    uint8_t mode{0};
    int32_t left_pwm{0};
    int32_t right_pwm{0};
  };

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
          return std::nullopt;  // Invalid number format
        }
        current.clear();
      }
    }
    if (!current.empty()) {
      try {
        values.push_back(std::stod(current));
      } catch (const std::exception &) {
        return std::nullopt;  // Invalid number format
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

  static std::string formatCommand(int32_t left_pwm, int32_t right_pwm)
  {
    std::ostringstream oss;
    oss << "C " << left_pwm << ' ' << right_pwm;
    return oss.str();
  }

  TcpClient client_;
  std::string host_;
  int port_{};
  double connect_timeout_{};
  std::chrono::duration<double> read_period_;
  std::chrono::duration<double> reconnect_delay_;
  std::chrono::duration<double> max_reconnect_delay_;
  std::chrono::duration<double> heartbeat_interval_;
  std::string stop_command_;
  std::string status_frame_id_;
  std::string handshake_;

  rclcpp::Publisher<thruster_control::msg::ThrusterStatusPWM>::SharedPtr status_pub_;
  rclcpp::Subscription<thruster_control::msg::ThrusterCmdPWM>::SharedPtr command_sub_;
  rclcpp::TimerBase::SharedPtr timer_;

  std::chrono::steady_clock::time_point next_reconnect_time_;
  std::chrono::steady_clock::time_point last_heartbeat_check_;
  int consecutive_failures_;

  // Stop command optimization
  std::chrono::steady_clock::time_point last_stop_command_time_;
  bool last_command_was_stop_{false};
  const std::chrono::steady_clock::duration stop_command_suppression_{std::chrono::seconds(3)};

  // Track last sent PWM values to check if thruster is already in stop state
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
