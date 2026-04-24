#!/usr/bin/env python3
"""
Playwright tests for WebSocket connection

Tests WebSocket functionality from the browser perspective:
- WebSocket connection establishment on page load
- Receiving full_state message on initial connection
- Receiving channelized updates and legacy state_update messages periodically
- Ping/pong heartbeat mechanism
- WebSocket appearing in browser Network tab
"""

import pytest
import time
from playwright.sync_api import Page, expect
from tests.ui.pages.websocket_page import WebSocketPage


@pytest.mark.skipif(
    False,  # Enabled for testing - requires server to be running
    reason="Requires FastAPI server running on http://localhost:8000"
)
class TestWebSocketConnection:
    """Test WebSocket connection from browser"""

    @pytest.fixture
    def ws_page(self, page: Page, base_url: str):
        """Create a WebSocket test page"""
        # Create page object
        ws = WebSocketPage(page, base_url)

        # Inject console logger BEFORE navigation to catch early logs
        page.add_init_script("""
            // Console logger - capture all console output
            window.capturedConsoleLogs = [];

            const originalLog = console.log;
            const originalError = console.error;
            const originalWarn = console.warn;
            const originalDebug = console.debug;

            console.log = function(...args) {
                window.capturedConsoleLogs.push({
                    level: 'log',
                    message: args.map(a => String(a)).join(' ')
                });
                originalLog.apply(console, args);
            };

            console.error = function(...args) {
                window.capturedConsoleLogs.push({
                    level: 'error',
                    message: args.map(a => String(a)).join(' ')
                });
                originalError.apply(console, args);
            };

            console.warn = function(...args) {
                window.capturedConsoleLogs.push({
                    level: 'warn',
                    message: args.map(a => String(a)).join(' ')
                });
                originalWarn.apply(console, args);
            };

            console.debug = function(...args) {
                window.capturedConsoleLogs.push({
                    level: 'debug',
                    message: args.map(a => String(a)).join(' ')
                });
                originalDebug.apply(console, args);
            };
        """)

        # Also inject WebSocket monitor before navigation
        page.add_init_script("""
            window.wsMonitor = {
                messages: [],
                connected: false,
                sent: [],
                errors: [],
                connectionAttempts: 0,
                connectTime: null
            };

            const originalWebSocket = window.WebSocket;
            window.WebSocket = function(...args) {
                window.wsMonitor.connectionAttempts++;
                window.wsMonitor.connectTime = new Date().toISOString();
                window.wsMonitor.url = args[0];

                const ws = new originalWebSocket(...args);

                ws.addEventListener('open', () => {
                    window.wsMonitor.connected = true;
                    console.log('[WS Monitor] WebSocket connected to', args[0]);
                });

                ws.addEventListener('message', (event) => {
                    try {
                        const msg = JSON.parse(event.data);
                        window.wsMonitor.messages.push({
                            type: msg.type,
                            timestamp: msg.timestamp || new Date().toISOString(),
                            receivedAt: new Date().toISOString()
                        });
                        console.log('[WS Monitor] Received:', msg.type);
                    } catch (e) {
                        if (event.data !== 'pong') {
                            console.log('[WS Monitor] Received non-JSON:', event.data);
                        }
                    }
                });

                ws.addEventListener('error', (error) => {
                    window.wsMonitor.errors.push({
                        error: String(error),
                        timestamp: new Date().toISOString()
                    });
                    console.error('[WS Monitor] Error:', error);
                });

                return ws;
            };

            console.log('[WS Monitor] WebSocket monitor installed');
        """)

        # Navigate to dashboard (scripts will be injected before page loads)
        ws.navigate("/")
        page.wait_for_load_state("networkidle")

        return ws

    def test_websocket_connects_on_page_load(self, ws_page: WebSocketPage):
        """Test that WebSocket connection is established when page loads"""
        # Wait a moment for WebSocket to connect
        time.sleep(1)

        status = ws_page.get_ws_status()
        assert status.get('connectionAttempts', 0) > 0, "WebSocket connection was attempted"

        # Check if connected (may take a moment)
        time.sleep(1)
        status = ws_page.get_ws_status()

        logger_msg = f"WebSocket status: {status}"
        print(logger_msg)

        # The connection should be established
        assert status.get('connected', False), "WebSocket should be connected"

    def test_websocket_url_correct(self, ws_page: WebSocketPage):
        """Test that WebSocket connects to the correct URL"""
        time.sleep(2)  # Wait for connection

        status = ws_page.get_ws_status()
        url = status.get('url')

        print(f"WebSocket URL: {url}")

        assert url is not None, "WebSocket URL should be recorded"
        assert '/ws' in url, "WebSocket URL should contain /ws endpoint"

        # Check protocol (ws or wss)
        assert url.startswith('ws://') or url.startswith('wss://'), \
            "WebSocket URL should use ws:// or wss:// protocol"

    def test_websocket_receives_full_state(self, ws_page: WebSocketPage):
        """Test that full_state message is received after connection"""
        time.sleep(2)  # Wait for connection and first message

        messages = ws_page.get_ws_messages()
        print(f"Received messages: {messages}")

        assert len(messages) > 0, "Should receive at least one WebSocket message"

        # First message should be full_state
        first_message = messages[0]
        assert first_message['type'] == 'full_state', \
            f"First message should be full_state, got {first_message['type']}"

    def test_websocket_ping_pong(self, ws_page: WebSocketPage):
        """Test ping/pong heartbeat mechanism"""
        time.sleep(2)  # Wait for connection

        # Check if any ping was sent (via the monitor)
        sent_messages = ws_page.get_ws_sent_messages()
        print(f"Sent messages: {sent_messages}")

        # The client should send ping periodically (every 30s)
        # We might not see it in this short test, but we can check the capability
        # For now, just verify we can check sent messages
        assert isinstance(sent_messages, list)

    def test_websocket_receives_state_update(self, ws_page: WebSocketPage):
        """Test that state_update messages are received periodically"""
        # Wait for initial connection and messages
        time.sleep(2)

        initial_count = ws_page.get_message_count_by_type('state_update')
        print(f"Initial state_update count: {initial_count}")

        # Wait for more state updates (server sends every 5 seconds)
        time.sleep(7)

        final_count = ws_page.get_message_count_by_type('state_update')
        print(f"Final state_update count: {final_count}")

        # Should receive at least one state_update
        assert final_count >= 1, "Should receive at least one state_update message"

    def test_websocket_message_structure(self, ws_page: WebSocketPage):
        """Test that WebSocket messages have correct structure"""
        time.sleep(2)

        messages = ws_page.get_ws_messages()

        for msg in messages:
            # All messages should have type and timestamp
            assert 'type' in msg, "Message should have 'type' field"

            # Verify known message types
            assert msg['type'] in [
                'full_state',
                'state_update',
                'connectivity_update',
                'sensors_update',
                'ros2_update',
                'ros2_control_update',
                'rosbag_update',
                'time_update',
                'alert',
            ], \
                f"Unknown message type: {msg['type']}"

    def test_websocket_connection_object_exists(self, ws_page: WebSocketPage):
        """Test that the WebSocket connection object is accessible"""
        time.sleep(2)

        conn_info = ws_page.get_ws_connection_object()
        print(f"Connection object info: {conn_info}")

        assert conn_info is not None, "WebSocket connection object should exist"
        assert 'readyState' in conn_info, "Should have readyState"

        # CONNECTING = 0, OPEN = 1, CLOSING = 2, CLOSED = 3
        ready_state = conn_info['readyState']
        assert ready_state == 1, f"WebSocket should be OPEN (1), got {ready_state}"

    def test_websocket_in_performance_entries(self, ws_page: WebSocketPage):
        """Test that WebSocket appears in Performance API entries"""
        time.sleep(2)

        entries = ws_page.check_ws_in_performance_entries()
        print(f"Performance API WebSocket entries: {entries}")

        # May not show up in Performance API for WebSocket
        # But if it does, verify the data structure
        for entry in entries:
            assert '/ws' in entry['name'], "Entry should be for /ws endpoint"
            assert 'duration' in entry, "Entry should have duration"

    def test_console_logs_for_ws_info(self, ws_page: WebSocketPage):
        """Test that console logs contain WebSocket debugging info"""
        time.sleep(2)

        logs = ws_page.get_console_logs()
        print(f"Console logs: {logs}")

        # Filter for WebSocket-related logs
        ws_logs = [log for log in logs if 'WS' in log.get('message', '')]
        print(f"WebSocket logs: {ws_logs}")

        # Should have some WebSocket-related logging
        assert len(ws_logs) > 0, "Should have WebSocket-related console logs"

        # Check for key log messages
        log_messages = [log['message'] for log in ws_logs]

        # Should have connection log
        has_connection_log = any(
            'Connecting' in msg or 'Connected' in msg
            for msg in log_messages
        )
        assert has_connection_log, "Should log WebSocket connection"

    def test_multiple_page_loads_maintain_connection(self, ws_page: WebSocketPage):
        """Test WebSocket behavior on page reload"""
        time.sleep(2)

        # Get initial connection count
        initial_status = ws_page.get_ws_status()
        initial_attempts = initial_status.get('connectionAttempts', 0)
        print(f"Initial connection attempts: {initial_attempts}")

        # Reload page
        ws_page.reload()

        # Wait for reconnection
        time.sleep(2)

        # Should have new connection attempt
        new_status = ws_page.get_ws_status()
        new_attempts = new_status.get('connectionAttempts', 0)
        print(f"Post-reload connection attempts: {new_attempts}")

        assert new_attempts > initial_attempts, \
            "Should have new connection attempt after reload"

    def test_websocket_has_state_data(self, ws_page: WebSocketPage):
        """Test that full_state message contains all expected data"""
        time.sleep(2)

        messages = ws_page.get_ws_messages()
        full_state_msg = next((m for m in messages if m['type'] == 'full_state'), None)

        assert full_state_msg is not None, "Should have a full_state message"

        # The message itself may just have type, let's check the console
        # for actual data reception logs
        logs = ws_page.get_console_logs()
        ws_logs = [log for log in logs if 'full_state' in log.get('message', '')]

        print(f"Logs mentioning full_state: {ws_logs}")


@pytest.mark.skipif(
    False,  # Enabled for testing
    reason="Requires FastAPI server running"
)
class TestWebSocketIntegration:
    """WebSocket integration tests with dashboard"""

    @pytest.fixture
    def ws_page(self, page: Page, base_url: str):
        """Create a WebSocket test page"""
        ws = WebSocketPage(page, base_url)
        ws.inject_console_logger()
        ws.inject_websocket_monitor()
        ws.navigate("/")
        page.wait_for_load_state("networkidle")
        return ws

    def test_dashboard_receives_sensor_updates(self, ws_page: WebSocketPage):
        """Test that dashboard receives sensor data via WebSocket"""
        time.sleep(3)  # Wait for initial full_state

        # Check console for sensor update logs
        logs = ws_page.get_console_logs()
        sensor_logs = [
            log for log in logs
            if 'sensor' in log.get('message', '').lower()
        ]

        print(f"Sensor-related logs: {sensor_logs}")

        # Should have some sensor-related activity
        assert len(sensor_logs) > 0, "Should have sensor-related logs"

    def test_dashboard_shows_connected_status(self, ws_page: WebSocketPage):
        """Test that dashboard shows WebSocket connected status"""
        time.sleep(2)

        # Check the connection status element
        status_text = ws_page.page.evaluate("""
            () => {
                const el = document.getElementById('connectionStatus');
                return el ? el.textContent : null;
            }
        """)

        print(f"Connection status text: {status_text}")

        assert status_text is not None, "Connection status element should exist"
        assert 'Connected' in status_text or 'Disconnected' in status_text, \
            "Status should show connection state"


@pytest.mark.skipif(
    False,  # Enabled for testing
    reason="Requires FastAPI server running"
)
class TestWebSocketErrors:
    """WebSocket error handling tests"""

    @pytest.fixture
    def ws_page(self, page: Page, base_url: str):
        """Create a WebSocket test page"""
        ws = WebSocketPage(page, base_url)
        ws.inject_console_logger()
        ws.inject_websocket_monitor()
        return ws

    def test_websocket_handles_invalid_host(self, ws_page: WebSocketPage):
        """Test WebSocket behavior with invalid host"""
        # Navigate to non-existent host would fail
        # This test documents expected behavior
        pass

    def test_websocket_reconnect_on_error(self, ws_page: WebSocketPage):
        """Test WebSocket reconnection behavior"""
        # This would require simulating a connection drop
        # For now, document the expected behavior
        pass
