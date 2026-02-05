# BatteryVoltage.msg
# Battery voltage monitoring message from ADS1115 ADC

std_msgs/Header header

# Channel voltages (V) - raw values, current conversion to be added later
float64 channel_a0    # A0: Messtechnik +
float64 channel_a1    # A1: Messtechnik -
float64 channel_a2    # A2: Antrieb +
float64 channel_a3    # A3: Antrieb -
