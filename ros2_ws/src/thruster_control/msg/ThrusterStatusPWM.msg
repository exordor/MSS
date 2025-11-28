# ThrusterStatusPWM.msg
std_msgs/Header header

# mode: 0 = RC, 1 = ROS
uint8 mode

# pwm: 1100 - 1900, 1500 = stop
int32 left_pwm
int32 right_pwm