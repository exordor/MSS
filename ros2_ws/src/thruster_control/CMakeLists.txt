cmake_minimum_required(VERSION 3.8)
project(thruster_control)

if(NOT CMAKE_CXX_STANDARD)
	set(CMAKE_CXX_STANDARD 17)
endif()

find_package(ament_cmake REQUIRED)
find_package(rclcpp REQUIRED)
find_package(std_msgs REQUIRED)
find_package(rosidl_default_generators REQUIRED)

set(msg_files
	"msg/ThrusterStatusPWM.msg"
	"msg/ThrusterCmdPWM.msg"
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

install(TARGETS thruster_node
	DESTINATION lib/${PROJECT_NAME})

ament_export_dependencies(rosidl_default_runtime)

ament_package()
