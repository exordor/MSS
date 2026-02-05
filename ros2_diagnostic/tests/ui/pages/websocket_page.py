# websocket_page.py - Page object for WebSocket testing

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeout
import logging
import json
from typing import Any, List, Dict, Optional
from tests.ui.pages.base_page import BasePage

logger = logging.getLogger(__name__)


class WebSocketPage(BasePage):
    """WebSocket connection and message testing page object"""

    def __init__(self, page: Page, base_url: str = "http://localhost:8000"):
        super().__init__(page, base_url)
        self.monitor_injected = False

    def inject_websocket_monitor(self) -> None:
        """Inject code to monitor WebSocket messages in the browser"""
        if self.monitor_injected:
            return

        monitor_script = """
        () => {
            if (window.wsMonitor) return;

            window.wsMonitor = {
                messages: [],
                connected: false,
                sent: [],
                errors: [],
                connectionAttempts: 0,
                connectTime: null
            };

            // Intercept WebSocket constructor
            const originalWebSocket = window.WebSocket;
            window.WebSocket = function(...args) {
                window.wsMonitor.connectionAttempts++;
                window.wsMonitor.connectTime = new Date().toISOString();

                const ws = new originalWebSocket(...args);
                window.wsMonitor.url = args[0];

                ws.addEventListener('open', () => {
                    window.wsMonitor.connected = true;
                    console.log('[WS Monitor] WebSocket connected');
                });

                ws.addEventListener('message', (event) => {
                    try {
                        const msg = JSON.parse(event.data);
                        window.wsMonitor.messages.push({
                            type: msg.type,
                            timestamp: msg.timestamp || new Date().toISOString(),
                            receivedAt: new Date().toISOString()
                        });
                    } catch (e) {
                        // ping/pong or other non-JSON messages
                        if (event.data !== 'pong') {
                            window.wsMonitor.messages.push({
                                raw: event.data,
                                receivedAt: new Date().toISOString()
                            });
                        }
                    }
                });

                ws.addEventListener('error', (error) => {
                    window.wsMonitor.errors.push({
                        error: String(error),
                        timestamp: new Date().toISOString()
                    });
                });

                ws.addEventListener('close', (event) => {
                    window.wsMonitor.connected = false;
                    window.wsMonitor.closeCode = event.code;
                    window.wsMonitor.closeReason = event.reason;
                });

                // Intercept send method
                const originalSend = ws.send.bind(ws);
                ws.send = function(data) {
                    window.wsMonitor.sent.push({
                        data: data,
                        timestamp: new Date().toISOString()
                    });
                    return originalSend(data);
                };

                return ws;
            };

            console.log('[WS Monitor] WebSocket monitor injected');
        }
        """

        self.page.evaluate(monitor_script)
        self.monitor_injected = True
        logger.info("WebSocket monitor injected")

    def get_ws_messages(self) -> List[Dict[str, Any]]:
        """Get captured WebSocket messages"""
        return self.page.evaluate("() => window.wsMonitor?.messages || []")

    def get_ws_sent_messages(self) -> List[Dict[str, Any]]:
        """Get messages sent via WebSocket"""
        return self.page.evaluate("() => window.wsMonitor?.sent || []")

    def get_ws_status(self) -> Dict[str, Any]:
        """Get WebSocket connection status and metadata"""
        return self.page.evaluate("""
            () => {
                if (!window.wsMonitor) return { error: 'Monitor not injected' };
                return {
                    connected: window.wsMonitor.connected,
                    url: window.wsMonitor.url || null,
                    connectionAttempts: window.wsMonitor.connectionAttempts || 0,
                    connectTime: window.wsMonitor.connectTime || null,
                    closeCode: window.wsMonitor.closeCode || null,
                    errors: window.wsMonitor.errors || []
                };
            }
        """)

    def get_ws_connection_object(self) -> Optional[Dict[str, Any]]:
        """Get the actual WebSocket connection object reference info"""
        return self.page.evaluate("""
            () => {
                if (window.wsConnection && window.wsConnection.ws) {
                    const ws = window.wsConnection.ws;
                    return {
                        readyState: ws.readyState,
                        url: ws.url,
                        protocol: ws.protocol,
                        bufferedAmount: ws.bufferedAmount
                    };
                }
                return null;
            }
        """)

    def wait_for_ws_message(self, message_type: str, timeout: int = 10000) -> Dict[str, Any]:
        """Wait for a specific type of WebSocket message"""
        start_time = __import__('time').time()

        while (__import__('time').time() - start_time) * 1000 < timeout:
            messages = self.get_ws_messages()
            for msg in messages:
                if msg.get('type') == message_type:
                    return msg
            __import__('time').sleep(0.1)

        raise PlaywrightTimeout(f"No '{message_type}' message received within {timeout}ms")

    def wait_for_ws_connected(self, timeout: int = 5000) -> bool:
        """Wait for WebSocket to be connected"""
        start_time = __import__('time').time()

        while (__import__('time').time() - start_time) * 1000 < timeout:
            if self.get_ws_status().get('connected'):
                return True
            __import__('time').sleep(0.1)

        raise PlaywrightTimeout(f"WebSocket not connected within {timeout}ms")

    def get_message_count_by_type(self, message_type: str) -> int:
        """Count messages of a specific type"""
        messages = self.get_ws_messages()
        return sum(1 for msg in messages if msg.get('type') == message_type)

    def get_console_logs(self) -> List[str]:
        """Get browser console logs (for debugging WebSocket issues)"""
        # Note: This requires console listener to be set up before navigation
        return self.page.evaluate("""
            () => {
                if (window.capturedConsoleLogs) {
                    return window.capturedConsoleLogs;
                }
                return [];
            }
        """)

    def inject_console_logger(self) -> None:
        """Inject console logger to capture all console output"""
        self.page.evaluate("""
            () => {
                if (window.capturedConsoleLogs) return;

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
            }
        """)
        logger.info("Console logger injected")

    def check_ws_in_performance_entries(self) -> List[Dict[str, Any]]:
        """Check Performance API for WebSocket entries"""
        return self.page.evaluate("""
            () => {
                const entries = performance.getEntriesByType('resource');
                return entries
                    .filter(e => e.name.includes('/ws'))
                    .map(e => ({
                        name: e.name,
                        duration: e.duration,
                        transferSize: e.transferSize,
                        encodedBodySize: e.encodedBodySize,
                        decodedBodySize: e.decodedBodySize,
                        startTime: e.startTime,
                        responseStatus: e.responseStatus || null
                    }));
            }
        """)
