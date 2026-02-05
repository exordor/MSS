#!/usr/bin/env python3
"""
Diagnostic Utility Functions
Shared utilities for diagnostic modules
"""

import socket
import subprocess
from typing import Dict, Any


def ping_host(host: str, timeout: int = 1, count: int = 2) -> Dict[str, Any]:
    """Ping a host and return results

    Reduced timeout from 2s/4count to 1s/2count to improve responsiveness.
    Total timeout is now ~3 seconds instead of 10.
    """
    try:
        result = subprocess.run(
            ['ping', '-c', str(count), '-W', str(timeout), host],
            capture_output=True,
            text=True,
            timeout=(timeout * count) + 1
        )

        output = result.stdout + result.stderr

        # Parse ping output
        packet_loss = 0
        avg_time = 0
        min_time = 0
        max_time = 0

        if 'packet loss' in output:
            try:
                loss_str = output.split('packet loss')[0].split(',')[-1].strip()
                packet_loss = float(loss_str.replace('%', ''))
            except (ValueError, IndexError):
                pass

        if 'min/avg/max' in output or 'rtt min/avg/max' in output:
            try:
                stats = output.split('=')[-1].strip()
                parts = stats.split('/')
                if len(parts) >= 3:
                    min_time = float(parts[0].strip().split()[0])
                    avg_time = float(parts[1].strip())
                    max_time = float(parts[2].strip().split()[0])
            except (ValueError, IndexError):
                pass

        return {
            'host': host,
            'reachable': result.returncode == 0,
            'packet_loss': packet_loss,
            'min_time_ms': min_time,
            'avg_time_ms': avg_time,
            'max_time_ms': max_time,
            'packet_count': count,
            'output': output,
        }

    except subprocess.TimeoutExpired:
        return {
            'host': host,
            'reachable': False,
            'packet_loss': 100,
            'error': 'timeout',
        }
    except Exception as e:
        return {
            'host': host,
            'reachable': False,
            'packet_loss': 100,
            'error': str(e),
        }


def check_tcp_connectivity_sync(host: str, port: int, timeout: float = 0.5) -> Dict[str, Any]:
    """Check TCP connectivity to host:port using socket

    Much faster than ping - only checks if the specific service port is open.
    Suitable for sensors with Web interfaces or known TCP ports.

    Args:
        host: IP address or hostname
        port: TCP port number
        timeout: Connection timeout in seconds (default 0.5)

    Returns:
        Dict with 'reachable' status and connection info
    """
    try:
        start_time = __import__('time').time()
        with socket.create_connection((host, port), timeout=timeout):
            latency_ms = (__import__('time').time() - start_time) * 1000
            return {
                'host': host,
                'port': port,
                'reachable': True,
                'latency_ms': round(latency_ms, 2),
                'method': 'tcp'
            }
    except socket.timeout:
        return {
            'host': host,
            'port': port,
            'reachable': False,
            'error': 'timeout',
            'method': 'tcp'
        }
    except (ConnectionRefusedError, OSError):
        return {
            'host': host,
            'port': port,
            'reachable': False,
            'error': 'connection_refused',
            'method': 'tcp'
        }
    except Exception as e:
        return {
            'host': host,
            'port': port,
            'reachable': False,
            'error': str(e),
            'method': 'tcp'
        }


def check_gige_camera_arp(camera_ip: str) -> Dict[str, Any]:
    """Check if GigE camera is present using ARP table

    GigE Vision uses custom UDP protocol, not standard TCP ports.
    ARP table is the most reliable way to detect presence on same subnet.
    This is much faster than ping (< 0.1 seconds).

    Args:
        camera_ip: IP address of the GigE camera

    Returns:
        Dict with 'reachable' status and ARP entry info
    """
    try:
        result = subprocess.run(
            ['ip', 'neigh', 'show', camera_ip],
            capture_output=True,
            text=True,
            timeout=1
        )
        # Parse ARP output
        # Format: 192.168.0.11 dev eth0 lladdr xx:xx:xx:xx:xx:xx REACHABLE
        # or: 192.168.0.11 dev eth0 FAILED
        if result.returncode == 0 and result.stdout.strip():
            lines = result.stdout.strip().split('\n')
            for line in lines:
                if camera_ip in line:
                    # Check for FAILED state first (camera unreachable)
                    if 'FAILED' in line:
                        return {
                            'host': camera_ip,
                            'reachable': False,
                            'method': 'arp',
                            'state': 'FAILED'
                        }
                    # Check for valid states with MAC address
                    has_mac = 'lladdr' in line
                    if 'REACHABLE' in line or 'STALE' in line or 'DELAY' in line:
                        return {
                            'host': camera_ip,
                            'reachable': True,
                            'method': 'arp',
                            'state': 'REACHABLE'
                        }
        return {
            'host': camera_ip,
            'reachable': False,
            'method': 'arp',
            'state': 'not_found'
        }
    except FileNotFoundError:
        # Fallback to /proc/net/arp if ip command not available
        try:
            with open('/proc/net/arp', 'r') as f:
                for line in f:
                    if camera_ip in line:
                        parts = line.split()
                        if len(parts) >= 6 and parts[3] != '00:00:00:00:00:00':
                            return {
                                'host': camera_ip,
                                'reachable': True,
                                'method': 'arp',
                                'state': 'found'
                            }
            return {
                'host': camera_ip,
                'reachable': False,
                'method': 'arp',
                'state': 'not_found'
            }
        except Exception:
            return {
                'host': camera_ip,
                'reachable': False,
                'method': 'arp',
                'error': 'arp_unavailable'
            }
    except Exception as e:
        return {
            'host': camera_ip,
            'reachable': False,
            'method': 'arp',
            'error': str(e)
        }

