# ConnectionStatus.msg
std_msgs/Header header

# WiFi UDP socket state
bool wifi_bound

# Arduino responding (timeout check)
bool arduino_online

# Total reconnect attempts since startup
uint32 reconnect_count

# Time since last successful reconnect (seconds)
float64 uptime_sec
