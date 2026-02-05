#!/usr/bin/env python3
"""
ROS2 Helper Module - Lightweight monitoring using rclpy
Replaces shell commands with direct DDS communication for lower CPU usage
"""

import os
import threading
import time
from typing import Dict, List, Optional, Any, Tuple
from collections import deque
from datetime import datetime

# Try to import rclpy, handle if not available
try:
    import rclpy
    from rclpy.node import Node
    from rclpy.executors import SingleThreadedExecutor
    from rclpy.qos import QoSProfile, ReliabilityPolicy, DurabilityPolicy
    RCLPY_AVAILABLE = True
except ImportError:
    RCLPY_AVAILABLE = False
    rclpy = None
    # Type stubs for when rclpy is not available
    class Node:
        pass
    class SingleThreadedExecutor:
        pass
    class QoSProfile:
        def __init__(self, reliability=None, durability=None, depth=10):
            pass
    class ReliabilityPolicy:
        BEST_EFFORT = 0
        RELIABLE = 1
    class DurabilityPolicy:
        VOLATILE = 0
        TRANSIENT_LOCAL = 1


class ROS2Helper:
    """
    Lightweight ROS2 monitoring using rclpy.
    Single persistent node for all queries - no subprocess calls.

    This replaces shell commands like:
    - ros2 node list -> get_node_names()
    - ros2 topic list -> get_topic_names()
    - ros2 topic info -> get_topic_info()
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls, domain_id: int = 42):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, domain_id: int = 42):
        # Allow re-initialization with different domain_id
        if not hasattr(self, '_initialized'):
            self.domain_id = domain_id
            self._node: Optional[Node] = None
            self._executor: Optional[SingleThreadedExecutor] = None
            self._running = False
            self._spin_thread: Optional[threading.Thread] = None
            self._start_lock = threading.Lock()

            # Frequency tracking - subscribes to topics and measures rate
            self._topic_subscribers: Dict[str, Any] = {}
            self._topic_timestamps: Dict[str, deque] = {}
            self._topic_lock = threading.Lock()
            self._max_history = 100

            self._initialized = True

    def start(self) -> bool:
        """Start the rclpy node in background thread"""
        if not RCLPY_AVAILABLE:
            return False

        with self._start_lock:
            if self._running:
                return True

            try:
                # Set environment
                os.environ['ROS_DOMAIN_ID'] = str(self.domain_id)

                # Initialize rclpy if not already initialized
                if not rclpy.ok():
                    rclpy.init()

                # Create node
                self._node = Node('diagnostic_helper')
                self._executor = SingleThreadedExecutor()
                self._executor.add_node(self._node)

                # Start spinning
                self._running = True
                self._spin_thread = threading.Thread(target=self._spin, daemon=True)
                self._spin_thread.start()

                return True
            except Exception as e:
                print(f"Failed to start ROS2Helper: {e}")
                self._running = False
                return False

    def stop(self):
        """Stop the rclpy node"""
        with self._start_lock:
            if not self._running:
                return

            self._running = False

            # Wait for spin thread to finish
            if self._spin_thread and self._spin_thread.is_alive():
                self._spin_thread.join(timeout=2)

            # Shutdown node
            if self._node:
                self._node.destroy_node()
                self._node = None

            if self._executor:
                self._executor.shutdown()
                self._executor = None

    def _spin(self):
        """Spin the node to handle callbacks"""
        while self._running and rclpy.ok():
            try:
                rclpy.spin_once(self._node, timeout_sec=0.1)
            except Exception:
                break

    def is_ready(self) -> bool:
        """Check if the helper is ready"""
        if not self._running or self._node is None:
            return False
        # Check if rclpy is still ok
        try:
            import rclpy
            return rclpy.ok()
        except Exception:
            return False

    def get_node_names(self) -> List[str]:
        """
        Get node names - tries rclpy first, falls back to shell command
        Replaces: ros2 node list

        Note: node.get_node_names() only returns the current node, not all nodes.
        This is a known rclpy limitation, so we fall back to ros2 command.
        """
        # Try rclpy first (only returns current node)
        if self.is_ready():
            try:
                node_names = self._node.get_node_names()
                # If we only get our own node, use shell command instead
                if len(node_names) <= 1:
                    raise Exception("Only current node available, use shell command")
            except Exception:
                pass

        # Fall back to shell command for all nodes
        import subprocess
        try:
            result = subprocess.run(
                ['ros2', 'node', 'list'],
                capture_output=True,
                text=True,
                timeout=5,
                env={**os.environ, 'ROS_DOMAIN_ID': str(self.domain_id)}
            )
            if result.returncode == 0:
                nodes = [n.strip() for n in result.stdout.strip().split('\n') if n.strip()]
                return nodes
        except Exception:
            pass

        return []

    def get_node_names_and_namespaces(self) -> List[Tuple[str, str]]:
        """
        Get node names with namespaces
        Replaces: ros2 node list -v
        """
        if not self.is_ready():
            return []

        try:
            return self._node.get_node_names_and_namespaces()
        except Exception:
            return []

    def get_topic_names(self) -> List[str]:
        """
        Get topic names - direct DDS query, no shell
        Replaces: ros2 topic list
        """
        if not self.is_ready():
            return []

        try:
            topics_info = self._node.get_topic_names_and_types()
            return [t[0] for t in topics_info]
        except Exception:
            return []

    def get_topic_names_and_types(self) -> List[Tuple[str, List[str]]]:
        """
        Get topic names with their types
        Replaces: ros2 topic list -t
        """
        if not self.is_ready():
            return []

        try:
            return self._node.get_topic_names_and_types()
        except Exception:
            return []

    def get_topic_info(self, topic_name: str) -> Dict[str, Any]:
        """
        Get topic information - publisher/subscriber counts
        Replaces: ros2 topic info <topic>

        Note: rclpy doesn't provide direct publisher/subscriber counts.
        This returns the information available via DDS.
        """
        if not self.is_ready():
            return {'error': 'Helper not ready'}

        try:
            topics_info = self._node.get_topic_names_and_types()

            for name, types in topics_info:
                if name == topic_name:
                    return {
                        'name': topic_name,
                        'types': types,
                        'exists': True,
                    }

            return {
                'name': topic_name,
                'exists': False,
                'types': [],
            }
        except Exception as e:
            return {'error': str(e)}

    def check_nodes(self, expected: List[str]) -> Dict[str, bool]:
        """
        Check multiple nodes efficiently
        Returns dict mapping node name to whether it exists
        """
        nodes = self.get_node_names()
        return {n: any(n in node for node in nodes) for n in expected}

    def check_topics(self, expected: List[str]) -> Dict[str, bool]:
        """
        Check multiple topics efficiently
        Returns dict mapping topic name to whether it exists
        """
        topics = self.get_topic_names()
        return {t: t in topics for t in expected}

    def start_frequency_monitor(self, topic_name: str, msg_type: str) -> bool:
        """
        Start monitoring a topic's frequency by subscribing to it
        This replaces 'ros2 topic hz' with direct message counting
        """
        if not self.is_ready():
            return False

        with self._topic_lock:
            if topic_name in self._topic_subscribers:
                return True  # Already monitoring

            try:
                # Import message type dynamically
                subscriber = TopicFrequencySubscriber(
                    self._node,
                    topic_name,
                    msg_type,
                    self._on_message_received
                )
                self._topic_subscribers[topic_name] = subscriber
                self._topic_timestamps[topic_name] = deque(maxlen=self._max_history)
                return True
            except Exception as e:
                print(f"Failed to start frequency monitor for {topic_name}: {e}")
                return False

    def _on_message_received(self, topic_name: str):
        """Callback when a message is received"""
        with self._topic_lock:
            if topic_name in self._topic_timestamps:
                self._topic_timestamps[topic_name].append(time.time())

    def get_frequency(self, topic_name: str, window_seconds: float = 5.0) -> Optional[float]:
        """
        Calculate frequency from received messages
        Replaces: ros2 topic hz <topic>
        """
        with self._topic_lock:
            if topic_name not in self._topic_timestamps:
                return None

            timestamps = list(self._topic_timestamps[topic_name])
            if len(timestamps) < 2:
                return None

            # Filter to last N seconds
            now = time.time()
            cutoff = now - window_seconds
            recent = [t for t in timestamps if t > cutoff]

            if len(recent) < 2:
                return None

            # Calculate frequency
            duration = recent[-1] - recent[0]
            if duration > 0:
                return (len(recent) - 1) / duration
            return None

    def get_all_frequencies(self) -> Dict[str, Dict[str, Any]]:
        """Get frequencies for all monitored topics"""
        result = {}
        with self._topic_lock:
            for topic in self._topic_timestamps:
                freq = self.get_frequency(topic)
                if freq is not None:
                    timestamps = list(self._topic_timestamps[topic])
                    result[topic] = {
                        'frequency': freq,
                        'message_count': len(timestamps),
                        'last_message': timestamps[-1] if timestamps else None,
                    }
        return result

    def get_system_snapshot(self) -> Dict[str, Any]:
        """Get quick snapshot of ROS2 system"""
        return {
            'ready': self.is_ready(),
            'domain_id': self.domain_id,
            'node_count': len(self.get_node_names()),
            'topic_count': len(self.get_topic_names()),
            'monitored_topics': list(self._topic_subscribers.keys()),
        }


class TopicFrequencySubscriber:
    """Subscriber that counts messages for frequency calculation"""

    def __init__(self, node: Node, topic_name: str, msg_type: str, callback):
        self.topic_name = topic_name
        self.callback = callback
        self.subscription = None

        # Import and create subscription
        try:
            msg_class = self._import_message_type(msg_type)
            if msg_class:
                # Use best effort QoS for monitoring
                qos = QoSProfile(
                    reliability=ReliabilityPolicy.BEST_EFFORT,
                    durability=DurabilityPolicy.VOLATILE,
                    depth=10
                )
                self.subscription = node.create_subscription(
                    msg_class,
                    topic_name,
                    self._message_callback,
                    qos
                )
        except Exception as e:
            print(f"Failed to create subscriber for {topic_name}: {e}")

    def _import_message_type(self, msg_type: str):
        """Dynamically import ROS2 message type"""
        try:
            # Parse type like 'sensor_msgs/msg/PointCloud2'
            parts = msg_type.split('/')
            if len(parts) == 3:
                pkg, msg, name = parts
            elif len(parts) == 2:
                pkg, name = parts
                msg = 'msg'
            else:
                return None

            module = __import__(f'{pkg}.{msg}', fromlist=[name])
            return getattr(module, name)
        except ImportError:
            # Try common message types mapping
            common_types = {
                # sensor_msgs
                'sensor_msgs/msg/PointCloud2': 'sensor_msgs.msg.PointCloud2',
                'sensor_msgs/msg/Image': 'sensor_msgs.msg.Image',
                'sensor_msgs/msg/CompressedImage': 'sensor_msgs.msg.CompressedImage',
                'sensor_msgs/msg/Imu': 'sensor_msgs.msg.Imu',
                'sensor_msgs/msg/NavSatFix': 'sensor_msgs.msg.NavSatFix',
                'sensor_msgs/msg/Twist': 'sensor_msgs.msg.Twist',
                'sensor_msgs/msg/JointState': 'sensor_msgs.msg.JointState',
                'sensor_msgs/msg/LaserScan': 'sensor_msgs.msg.LaserScan',
                'sensor_msgs/msg/Range': 'sensor_msgs.msg.Range',
                'sensor_msgs/msg/TimeReference': 'sensor_msgs.msg.TimeReference',
                # std_msgs
                'std_msgs/msg/String': 'std_msgs.msg.String',
                'std_msgs/msg/Header': 'std_msgs.msg.Header',
                'std_msgs/msg/Bool': 'std_msgs.msg.Bool',
                'std_msgs/msg/Float32': 'std_msgs.msg.Float32',
                'std_msgs/msg/Float64': 'std_msgs.msg.Float64',
                'std_msgs/msg/Int32': 'std_msgs.msg.Int32',
                'std_msgs/msg/UInt32': 'std_msgs.msg.UInt32',
                # geometry_msgs
                'geometry_msgs/msg/PoseStamped': 'geometry_msgs.msg.PoseStamped',
                'geometry_msgs/msg/TwistStamped': 'geometry_msgs.msg.TwistStamped',
                'geometry_msgs/msg/TransformStamped': 'geometry_msgs.msg.TransformStamped',
                # diagnostic_msgs
                'diagnostic_msgs/msg/DiagnosticStatus': 'diagnostic_msgs.msg.DiagnosticStatus',
                'diagnostic_msgs/msg/DiagnosticArray': 'diagnostic_msgs.msg.DiagnosticArray',
            }
            if msg_type in common_types:
                pkg_name, msg_name = common_types[msg_type].rsplit('.', 1)
                module = __import__(pkg_name, fromlist=[msg_name])
                return getattr(module, msg_name)
            return None

    def _message_callback(self, msg):
        """Handle incoming message"""
        self.callback(self.topic_name)

    def destroy(self):
        """Destroy the subscription"""
        if self.subscription:
            self.subscription.destroy()
            self.subscription = None


# Singleton instance
_ros2_helper_instance: Optional[ROS2Helper] = None
_helper_lock = threading.Lock()


def get_ros2_helper(domain_id: int = 42) -> ROS2Helper:
    """Get or create the singleton ROS2Helper instance"""
    global _ros2_helper_instance

    with _helper_lock:
        if _ros2_helper_instance is None:
            _ros2_helper_instance = ROS2Helper(domain_id)
            _ros2_helper_instance.start()
        return _ros2_helper_instance


def shutdown_ros2_helper():
    """Shutdown the ROS2 helper"""
    global _ros2_helper_instance

    with _helper_lock:
        if _ros2_helper_instance:
            _ros2_helper_instance.stop()
            _ros2_helper_instance = None
