# Project Name

Multi-Sensor Floating System (ROS1 + ROS2 Hybrid Architecture)

# Overview

This project implements a hybrid ROS1 + ROS2 multi-sensor system running on a Jetson (JetPack 5.1.2, Ubuntu 20.04).
It supports:

ROS1 Noetic (host)

ROS2 (Docker)

Hesai LiDAR (ROS1 + ROS2)

SBG IMU (ROS1 + ROS2)

Camera driver (ROS1)

ros1_bridge

SLAM (optional: Fast-LVIO2 / MOLA)

The project is designed for gradual migration from ROS1 → ROS2, modular bringup, and clean configuration management.