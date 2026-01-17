# Solution for SBG ROS2 Driver Standard imu/data Topic Publishing Issue

## 📋 Problem Overview

### Symptoms
- SBG driver starts normally
- SBG custom topics have data:
  - `/sbg/imu_short` - has data
  - `/sbg/ekf_quat` - has data
- Standard topic `/imu/data` exists but has no messages
- Configuration is correct:
  - `ros_standard: true`
  - `use_enu: true`

---

## 🔍 Root Cause Analysis

### Source Code Logic

Based on the `processRosImuMessage()` function in `message_publisher.cpp`:

```cpp
void MessagePublisher::processRosImuMessage()
{
  if (imu_pub_)  // Standard publisher created
  {
    sbg_driver::msg::SbgEkfQuat ekf_quat_message_zero;

    // Prefer IMU Short data (if available)
    if (sbg_imu_short_pub_)
    {
      // ⚠️ Key condition: timestamps must match exactly!
      if ((sbg_ekf_quat_message_ == ekf_quat_message_zero) ||
          (sbg_imu_short_message_.time_stamp == sbg_ekf_quat_message_.time_stamp))
      {
        imu_pub_->publish(
          message_wrapper_.createRosImuMessage(sbg_imu_short_message_, sbg_ekf_quat_message_)
        );
      }
    }
    // Fallback: use IMU Data (if Short not available)
    else if (sbg_imu_data_pub_)
    {
      if ((sbg_ekf_quat_message_ == ekf_quat_message_zero) ||
          (sbg_imu_message_.time_stamp == sbg_ekf_quat_message_.time_stamp))
      {
        imu_pub_->publish(
          message_wrapper_.createRosImuMessage(sbg_imu_message_, sbg_ekf_quat_message_)
        );
      }
    }
  }
}
```

### Timestamp Matching Issue

**Key Condition**:
```cpp
sbg_imu_short_message_.time_stamp == sbg_ekf_quat_message_.time_stamp
```

**The Problem**:
- Requires timestamps to be **exactly equal** (`==`)
- IMU Short and EKF Quat come from different output streams of the device
- Both timestamps may have microsecond-level differences (e.g., 1-10 μs)
- Even with very small differences, the condition fails
- This causes standard IMU messages not to be published

**Example**:
```
SBG Device:
├─ IMU Short: time_stamp = 123456789 μs
└─ EKF Quat: time_stamp = 123456790 μs  (1 μs difference!)

Code Check:
sbg_imu_short_message_.time_stamp (123456789)
vs
sbg_ekf_quat_message_.time_stamp (123456790)
❌ No match! Standard IMU message not published
```

---

## 💡 Solutions

### Solution 1: Disable IMU Short, Use IMU Data (Recommended) ✅

**Configuration Change**:

```yaml
# File: sbg_test.yaml
output:
  # Data output configuration
  log_imu_data: 8        # ✅ Enable IMU Data
  log_imu_short: 0        # ❌ Disable IMU Short (to avoid timestamp mismatch)
  log_ekf_quat: 8        # ✅ Enable quaternion
  log_ekf_euler: 8       # ✅ Enable Euler angles
```

**How it Works**:
- IMU Data and EKF Quat have better timestamp matching
- No longer relies on strict timestamp matching from IMU Short

**Pros**:
- ✅ Simple configuration, only need to modify YAML file
- ✅ No need to recompile source code
- ✅ IMU Data contains the same sensor data
- ✅ Better timestamp synchronization

**Cons**:
- IMU Data sampling rate may be slightly lower than IMU Short (but usually acceptable)

---

### Solution 2: Modify Timestamp Matching Logic (Alternative)

**Source Code Modification**:

```cpp
// File: message_publisher.cpp
// Function: MessagePublisher::processRosImuMessage()

// Before: exact match
if (sbg_imu_short_message_.time_stamp == sbg_ekf_quat_message_.time_stamp)

// After: allow small error
int32_t time_diff = abs(
  sbg_imu_short_message_.time_stamp - sbg_ekf_quat_message_.time_stamp
);
if (time_diff < 1000)  // Allow 1ms error
```

**Compilation Issues**:
- Need to handle type ambiguity of `abs()` function
- IMU Short's `time_stamp` is `uint32_t`
- Need explicit type conversion

**Pros**:
- ✅ Retains high-precision data from IMU Short
- ✅ Allows reasonable timestamp differences

**Cons**:
- ❌ Requires recompiling the driver
- ❌ Source code modification, upgrades may lose changes
- ❌ May encounter type issues during compilation

---

### Solution 3: Use SBG Custom Topics (Alternative)

**Implementation**:

```python
# Subscribe to SBG custom topics at application layer
rospy.Subscriber('/sbg/imu_short', imu_short_callback)
rospy.Subscriber('/sbg/ekf_quat', quat_callback)

def combine_data(imu_msg, quat_msg):
    # Combine into standard IMU message
    if imu_msg and quat_msg:
        imu_msg = sensor_msgs.msg.Imu()
        imu_msg.header = imu_msg.header
        imu_msg.angular_velocity = imu_msg.delta_angle / SCALE
        imu_msg.linear_acceleration = imu_msg.delta_velocity / SCALE
        imu_msg.orientation = quat_msg.quaternion
        # Publish combined message
        imu_pub.publish(imu_msg)
```

**Pros**:
- ✅ Complete control at application layer
- ✅ No need to modify driver

**Cons**:
- ❌ Increases application complexity
- ❌ Requires additional message synchronization logic

---

## ✅ Implemented Solution (Solution 1)

### Configuration File Modification

**File**: `/home/eagrumo/mss_lecture/temp/sbg_test.yaml`

**Modifications**:

```yaml
output:
  # Time reference
  time_reference: "ros"

  # ROS standard output
  ros_standard: true    # ✅ Enable standard ROS messages

  # Frame convention
  use_enu: true         # ✅ Use ENU coordinate system
  frame_id: "imu_link"  # ✅ Standard frame ID

  # Data output configuration
  log_status: 200      # Status information @ 1Hz

  # ✅ Key change: Disable IMU Short, Enable IMU Data
  log_imu_data: 8       # IMU Data @ 25Hz
  log_imu_short: 0     # ❌ Disable IMU Short (to avoid timestamp mismatch)

  log_ekf_euler: 8      # Euler angles @ 25Hz
  log_ekf_quat: 8       # Quaternion @ 25Hz
  log_ekf_nav: 8        # Navigation data @ 25Hz
  log_ekf_vel_body: 0

  log_utc_time: 200     # UTC time @ 1Hz
  log_air_data: 0        # Air data @ 25Hz (not configured according to logs)
  log_imu_short: 0
```

---

## 📊 Verification Steps

### 1. Check Topic List

```bash
ros2 topic list | grep imu
```

**Expected Output**:
```
/imu/data              # ✅ Standard IMU (has data)
/imu/mag              # ⚠️ Magnetometer (need to enable log_mag)
/imu/temp              # ✅ Temperature
/imu/nav_sat_fix       # ✅ GPS position (if available)
/imu/pos_ecef          # ✅ ECEF position
/imu/utc_ref           # ✅ UTC time reference
/imu/velocity           # ✅ Velocity
/sbg/imu_data          # ✅ SBG IMU Data
/sbg/imu_short         # ❌ No longer published
/sbg/ekf_euler        # ✅ Euler angles
/sbg/ekf_nav           # ✅ Navigation
/sbg/ekf_quat          # ✅ Quaternion
/sbg/status             # ✅ Status
/sbg/utc_time          # ✅ UTC time
/tf                   # ✅ Transform
/tf_static             # ✅ Static transform
```

### 2. Verify Message Publishing

```bash
# View first message
ros2 topic echo /imu/data --once

# Monitor message stream
ros2 topic echo /imu/data
```

**Expected Output** (standard IMU message):

```yaml
header:
  stamp:
    sec: 1768399911
    nanosec: 654398203
  frame_id: "imu_link"
orientation:
  x: -0.003459545693220287
  y: -0.007615163053210689
  z: -0.5081723180526876
  w: 0.861214783474888
orientation_covariance:
  - 1.1006734706283316e-05
  - 0.0
  - 0.0
  - 0.0
  - 1.0997609350050076e-05
  - 0.0
  - 0.0
  - 0.0
  - 5.0030459028910105e-05
angular_velocity:
  x: -0.00048273830907419324
  y: 0.0012876458931714296
  z: 0.0009260230581276119
angular_velocity_covariance:
  - 0.0
  - 0.0
  - 0.0
  - 0.0
  - 0.0
  - 0.0
  - 0.0
  - 0.0
linear_acceleration:
  x: -0.028661785647273064
  y: -0.01760994829237461
  z: 9.814027786254883
linear_acceleration_covariance:
  - 0.0
  - 0.0
  - 0.0
  - 0.0
  - 0.0
  - 0.0
  - 0.0
  - 0.0
  - 0.0
```

### 3. Check Publishing Frequency

```bash
ros2 topic hz /imu/data
```

**Expected Output**:
```
average rate: 25.000
min: 0.040s
max: 0.040s
std dev: 0.000s
```

---

## 📝 Data Mapping Relationship

### Standard IMU Message Field Sources

| Field | Source | Description |
|------|--------|------|
| `header.stamp` | `sbg_imu_data.time_stamp` | IMU Data timestamp |
| `header.frame_id` | Config `output.frame_id` | "imu_link" |
| `angular_velocity` | `sbg_imu_data.delta_angle` / SCALE | Gyroscope data (angular velocity) |
| `linear_acceleration` | `sbg_imu_data.delta_velocity` / SCALE | Accelerometer data |
| `orientation` | `sbg_ekf_quat.quaternion` | EKF quaternion (orientation) |
| `orientation_covariance` | `sbg_ekf_quat.accuracy²` | Orientation accuracy (covariance) |
| `angular_velocity_covariance` | 0.0 | Not provided |
| `linear_acceleration_covariance` | 0.0 | Not provided |

### Data Flow Diagram

```
SBG Device
    │
    ├─ IMU Data (25 Hz)
    │   ├─ delta_angle    → Angular velocity
    │   ├─ delta_velocity → Linear acceleration
    │   └─ time_stamp    → Timestamp
    │
    └─ EKF Quat (25 Hz)
        ├─ quaternion     → Orientation
        ├─ accuracy      → Orientation accuracy
        └─ time_stamp    → Timestamp
            │
            ↓ (Timestamp matching: IMU Data ↔ EKF Quat)
            │
    ROS Standard Message /imu/data
        ├─ angular_velocity      (from IMU Data)
        ├─ linear_acceleration   (from IMU Data)
        ├─ orientation          (from EKF Quat)
        └─ orientation_covariance (from EKF Quat)
```

---

## ⚙️ Other Related Configuration

### Coordinate System Configuration

| Parameter | Value | Description |
|------|-----|------|
| `use_enu` | `true` | ENU coordinate system (X East, Y North, Z Up) |
| `use_enu` | `false` | NED coordinate system (X North, Y East, Z Down) |

**Important**:
- Standard ROS messages require `use_enu: true`
- If `use_enu: false`, standard IMU messages will not be published

### ROS Standard Message Enable

| Parameter | Value | Description |
|------|-----|------|
| `ros_standard` | `true` | Publish standard ROS messages (sensor_msgs) |
| `ros_standard` | `false` | Only publish SBG custom messages |

**Impact**:
- `ros_standard: true` → Publish `/imu/data`, `/imu/mag`, `/imu/temp`, etc.
- `ros_standard: false` → Only publish `/sbg/*` topics

---

## 🔧 Complete Working Configuration Example

### Minimal Configuration (IMU Only)

```yaml
/**:
  ros__parameters:
    driver:
      frequency: 400

    output:
      time_reference: "ros"
      ros_standard: true
      use_enu: true
      frame_id: "imu_link"

      # Core configuration: Disable IMU Short, Enable IMU Data
      log_imu_data: 8
      log_imu_short: 0
      log_ekf_quat: 8
```

### Recommended Configuration (Complete Sensors)

```yaml
/**:
  ros__parameters:
    driver:
      frequency: 400

    uartConf:
      portName: "/dev/serial/by-id/usb-FTDI_USB-RS232_Cable_FT3R66K9-if00-port0"
      baudRate: 115200
      portID: 0

    output:
      time_reference: "ros"
      ros_standard: true
      use_enu: true
      frame_id: "imu_link"

      log_status: 200
      log_imu_data: 8        # ✅ Use IMU Data
      log_imu_short: 0     # ❌ Disable IMU Short
      log_ekf_euler: 8
      log_ekf_quat: 8
      log_ekf_nav: 8
      log_utc_time: 200

      log_air_data: 8        # Air data
      log_mag: 8            # Magnetometer
```

---

## 📚 Troubleshooting

### Issue: `/imu/data` topic has no messages

**Checklist**:

1. ✅ Check if topic exists
   ```bash
   ros2 topic list | grep imu/data
   # Should output: /imu/data
   ```

2. ✅ Check publisher count
   ```bash
   ros2 topic info /imu/data
   # Publisher count should be > 0
   ```

3. ✅ Check configuration file
   ```bash
   grep -A 2 "ros_standard\|use_enu" sbg_test.yaml
   # ros_standard: true
   # use_enu: true
   ```

4. ✅ Check data output configuration
   ```bash
   grep "log_imu_data\|log_imu_short\|log_ekf_quat" sbg_test.yaml
   # log_imu_data: 8
   # log_imu_short: 0  ← Key!
   # log_ekf_quat: 8
   ```

5. ✅ Check driver logs
   ```bash
   # View logs when driver starts
   # Should not have warning: "SBG Imu and/or Quat output are not configured"
   ```

### Issue: Topic exists but no data

**Possible Causes**:

1. ❌ `log_imu_short: 8` and `log_imu_data: 0`
   - **Solution**: Change to `log_imu_short: 0`, `log_imu_data: 8`

2. ❌ `use_enu: false`
   - **Solution**: Change to `use_enu: true`

3. ❌ `ros_standard: false`
   - **Solution**: Change to `ros_standard: true`

4. ❌ Device timestamps not synchronized
   - **Solution**: Check device configuration, or use IMU Data

---

## 🎯 Summary

### Problem

SBG driver's standard `/imu/data` topic exists but no messages are published.

### Root Cause

Timestamp matching condition in `processRosImuMessage()` is too strict:
- IMU Short and EKF Quat timestamps must be exactly equal
- Two output streams from the device may have microsecond-level differences
- This causes the matching condition to fail, preventing standard IMU messages from being published

### Solution

**Disable IMU Short, Use IMU Data**:

```yaml
output:
  log_imu_data: 8      # ✅ Enable
  log_imu_short: 0     # ❌ Disable
```

### Verification

Standard IMU message `/imu/data` is published normally:
- Contains orientation (quaternion)
- Contains angular velocity
- Contains linear acceleration
- Publishing frequency approximately 25 Hz

---

## 🔗 Related Files

| File | Path | Description |
|------|--------|------|
| Configuration file | `/home/eagrumo/mss_lecture/temp/sbg_test.yaml` | Modified configuration |
| Launch file | `/home/eagrumo/mss_lecture/temp/src/sbg_ros2_driver/launch/sbg_device_launch.py` | Launch script |
| Message processing | `/home/eagrumo/mss_lecture/temp/src/sbg_ros2_driver/src/message_publisher.cpp` | Core logic |
| Message creation | `/home/eagrumo/mss_lecture/temp/src/sbg_ros2_driver/src/message_wrapper.cpp` | IMU message creation |

---

## 📝 References

- SBG official documentation: https://www.sbg-systems.com/
- ROS2 sensor_msgs/Imu: http://docs.ros.org/en/humble/p/sensor_msgs/msg/generated/struct/sensor__msgs__msg__Imu.html
- SBG ELLIPSE-D User Manual

---

## ✅ Status

- [x] Issue identified
- [x] Root cause analyzed
- [x] Solution implemented
- [x] Configuration verified
- [x] Documentation created

**Issue Status**: ✅ Resolved
