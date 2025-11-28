#include <rclcpp/rclcpp.hpp>
#include "thruster_control/msg/thruster_cmd_pwm.hpp"
#include "thruster_control/msg/thruster_status_pwm.hpp"

#include <algorithm>
#include <chrono>
#include <cerrno>
#include <cmath>
#include <cctype>
#include <cstdint>
#include <cstring>
#include <fcntl.h>
#include <memory>
#include <optional>
#include <sstream>
#include <string>
#include <sys/ioctl.h>
#include <termios.h>
#include <unistd.h>
#include <vector>

namespace thruster_control
{

class SerialPort
{
public:
  SerialPort() = default;
  ~SerialPort() { close(); }

  bool open(const std::string & device, int baud_rate)
  {
    close();
    last_error_.clear();

    fd_ = ::open(device.c_str(), O_RDWR | O_NOCTTY | O_NONBLOCK);
    if (fd_ < 0) {
      last_error_ = std::strerror(errno);
      return false;
    }

    struct termios tty;
    if (tcgetattr(fd_, &tty) != 0) {
      last_error_ = std::strerror(errno);
      close();
      return false;
    }

    cfmakeraw(&tty);

    speed_t speed = toSpeedConstant(baud_rate);
    if (cfsetispeed(&tty, speed) != 0 || cfsetospeed(&tty, speed) != 0) {
      last_error_ = std::strerror(errno);
      close();
      return false;
    }

    tty.c_cflag |= (CLOCAL | CREAD);
    tty.c_cflag &= ~(PARENB | PARODD | CSTOPB | CRTSCTS);
    tty.c_cflag &= ~CSIZE;
    tty.c_cflag |= CS8;

    tty.c_cc[VMIN] = 0;
    tty.c_cc[VTIME] = 0;

    if (tcsetattr(fd_, TCSANOW, &tty) != 0) {
      last_error_ = std::strerror(errno);
      close();
      return false;
    }

    buffer_.clear();
    return true;
  }

  void close()
  {
    if (fd_ >= 0) {
      ::close(fd_);
      fd_ = -1;
    }
    buffer_.clear();
  }

  bool isOpen() const { return fd_ >= 0; }

  const std::string & lastError() const { return last_error_; }

  bool writeLine(const std::string & line)
  {
    if (!isOpen()) {
      last_error_ = "serial port closed";
      return false;
    }

    std::string payload = line;
    if (payload.empty() || payload.back() != '\n') {
      payload.push_back('\n');
    }

    const char * data = payload.c_str();
    size_t remaining = payload.size();
    while (remaining > 0) {
      ssize_t written = ::write(fd_, data, remaining);
      if (written < 0) {
        if (errno == EINTR) {
          continue;
        }
        last_error_ = std::strerror(errno);
        return false;
      }
      remaining -= static_cast<size_t>(written);
      data += written;
    }

    tcdrain(fd_);
    return true;
  }

  bool readLines(std::vector<std::string> & lines)
  {
    if (!isOpen()) {
      return false;
    }

    bool read_any = false;
    char buf[256];
    while (true) {
      ssize_t n = ::read(fd_, buf, sizeof(buf));
      if (n > 0) {
        read_any = true;
        buffer_.append(buf, static_cast<size_t>(n));
        std::string line;
        while (extractLine(line)) {
          lines.emplace_back(std::move(line));
        }
      } else if (n == 0) {
        break;
      } else {
        if (errno == EAGAIN || errno == EWOULDBLOCK) {
          break;
        }
        last_error_ = std::strerror(errno);
        break;
      }
    }
    return read_any;
  }

private:
  bool extractLine(std::string & line)
  {
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

  static speed_t toSpeedConstant(int baud)
  {
    switch (baud) {
      case 9600:
        return B9600;
      case 19200:
        return B19200;
      case 38400:
        return B38400;
      case 57600:
        return B57600;
      case 115200:
      default:
        return B115200;
    }
  }

  int fd_{-1};
  std::string buffer_;
  std::string last_error_;
};

class ThrusterNode : public rclcpp::Node
{
public:
  ThrusterNode()
  : rclcpp::Node("thruster_node")
  {
    port_path_ = declare_parameter<std::string>(
      "port", "/dev/serial/by-id/usb-Arduino_UNO_WiFi_R4_CMSIS-DAP_64E8335D6BF8-if01");
    baud_rate_ = declare_parameter<int>("baud", 115200);
    read_period_ = std::chrono::duration<double>(declare_parameter<double>("read_interval", 0.05));
    stop_command_ = declare_parameter<std::string>("stop_cmd", "C 1500 1500");
    status_frame_id_ = declare_parameter<std::string>("status_frame_id", "thruster_link");

    status_pub_ = create_publisher<thruster_control::msg::ThrusterStatusPWM>("thruster_status_pwm", 10);
    command_sub_ = create_subscription<thruster_control::msg::ThrusterCmdPWM>(
      "thruster_cmd_pwm", 10,
      std::bind(&ThrusterNode::handleCommand, this, std::placeholders::_1));

    timer_ = create_wall_timer(read_period_, std::bind(&ThrusterNode::pollSerial, this));

    if (serial_.open(port_path_, baud_rate_)) {
      RCLCPP_INFO(get_logger(), "Opened serial port %s @ %d", port_path_.c_str(), baud_rate_);
      rclcpp::sleep_for(std::chrono::seconds(2));
    } else {
      RCLCPP_ERROR(get_logger(), "Failed to open %s: %s", port_path_.c_str(), serial_.lastError().c_str());
    }
  }

  ~ThrusterNode() override
  {
    if (!stop_command_.empty()) {
      (void)serial_.writeLine(stop_command_);
    }
    serial_.close();
  }

private:
  void handleCommand(const thruster_control::msg::ThrusterCmdPWM::SharedPtr msg)
  {
    if (!serial_.isOpen()) {
      RCLCPP_WARN_THROTTLE(get_logger(), *get_clock(), 2000, "Serial port not open; command dropped");
      return;
    }

    const std::string payload = formatCommand(msg->left_pwm, msg->right_pwm);
    if (!serial_.writeLine(payload)) {
      RCLCPP_ERROR(get_logger(), "Failed to write command: %s", serial_.lastError().c_str());
      return;
    }
    RCLCPP_INFO(get_logger(), "TX PWM: %s", payload.c_str());
  }

  void pollSerial()
  {
    if (!serial_.isOpen()) {
      return;
    }

    std::vector<std::string> lines;
    serial_.readLines(lines);
    for (auto & line : lines) {
      auto parsed = parseStatus(line);
      if (!parsed.has_value()) {
        continue;
      }

      thruster_control::msg::ThrusterStatusPWM msg;
      msg.header.stamp = this->get_clock()->now();
      msg.header.frame_id = status_frame_id_;
      msg.mode = parsed->mode;
      msg.left_pwm = parsed->left_pwm;
      msg.right_pwm = parsed->right_pwm;
      status_pub_->publish(msg);
      RCLCPP_INFO(get_logger(), "RX PWM: %s", line.c_str());
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
        values.push_back(std::stod(current));
        current.clear();
      }
    }
    if (!current.empty()) {
      values.push_back(std::stod(current));
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

  SerialPort serial_;
  std::string port_path_;
  int baud_rate_{};
  std::chrono::duration<double> read_period_;
  std::string stop_command_;
  std::string status_frame_id_;

  rclcpp::Publisher<thruster_control::msg::ThrusterStatusPWM>::SharedPtr status_pub_;
  rclcpp::Subscription<thruster_control::msg::ThrusterCmdPWM>::SharedPtr command_sub_;
  rclcpp::TimerBase::SharedPtr timer_;
};

}  // namespace thruster_control

int main(int argc, char ** argv)
{
  rclcpp::init(argc, argv);
  auto node = std::make_shared<thruster_control::ThrusterNode>();
  rclcpp::spin(node);
  rclcpp::shutdown();
  return 0;
}
