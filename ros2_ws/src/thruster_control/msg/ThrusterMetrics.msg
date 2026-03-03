# ThrusterMetrics.msg
std_msgs/Header header

# Data statistics
uint32 tx_packets      # Total packets sent
uint32 rx_packets      # Total packets received
uint32 rx_heartbeat    # Heartbeat packets received
uint32 rx_status       # Status messages received
uint32 rx_speed        # Speed data messages received
uint32 rx_temp_humidity  # Temp/Humidity messages received
uint32 parse_errors    # Failed message parses
uint32 timeouts        # Timeout events

# Performance metrics
float64 latency_ms     # Round-trip latency (PING/PONG)
float64 loop_time_ms   # Main loop execution time
float64 throughput_bps # Data throughput (bytes/sec)

# Error rates
float64 error_rate     # Parse errors / total RX (%)
