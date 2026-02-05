# SpeedData.msg
std_msgs/Header header

# Sensor frequency in Hz
float64 freq_hz

# Flow rate in L/min (for calibration)
float64 flow_lmin

# Water velocity in m/s (primary measurement)
float64 velocity_ms

# Total volume in liters
float64 total_liters
