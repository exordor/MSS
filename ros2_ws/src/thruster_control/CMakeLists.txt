cmake_minimum_required(VERSION 3.8)
project(thruster_control)

if(NOT CMAKE_CXX_STANDARD)
	set(CMAKE_CXX_STANDARD 17)
endif()

find_package(ament_cmake REQUIRED)
find_package(rclcpp REQUIRED)
find_package(std_msgs REQUIRED)
find_package(rosidl_default_generators REQUIRED)
find_package(nlohmann_json REQUIRED)
find_library(PAHO_MQTTPP_LIB paho-mqttpp3)
find_library(PAHO_MQTT_C_LIB paho-mqtt3as)

set(msg_files
	"msg/ThrusterStatusPWM.msg"
	"msg/ThrusterCmdPWM.msg"
	"msg/SpeedData.msg"
	"msg/TempHumidity.msg"
	"msg/ConnectionStatus.msg"
	"msg/ThrusterMetrics.msg"
	"msg/WaterQuality.msg"
	"msg/UpsStatus.msg"
)

rosidl_generate_interfaces(${PROJECT_NAME}
	${msg_files}
	DEPENDENCIES std_msgs
)

add_executable(thruster_node src/thruster_node.cpp)
ament_target_dependencies(thruster_node rclcpp std_msgs)

rosidl_target_interfaces(thruster_node
	${PROJECT_NAME}
	"rosidl_typesupport_cpp")

add_executable(thruster_wifi_node src/thruster_wifi_node.cpp)
ament_target_dependencies(thruster_wifi_node rclcpp std_msgs)
target_link_libraries(thruster_wifi_node ${PAHO_MQTTPP_LIB} ${PAHO_MQTT_C_LIB})
target_link_libraries(thruster_wifi_node nlohmann_json::nlohmann_json)

rosidl_target_interfaces(thruster_wifi_node
	${PROJECT_NAME}
	"rosidl_typesupport_cpp")

install(TARGETS
	thruster_node
	thruster_wifi_node
	DESTINATION lib/${PROJECT_NAME})

ament_export_dependencies(rosidl_default_runtime)

ament_package()
