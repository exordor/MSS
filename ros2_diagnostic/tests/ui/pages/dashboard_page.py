# dashboard_page.py - Page Object for the Dashboard page

from playwright.sync_api import Page, Locator
import re
from typing import Dict, Any
from .base_page import BasePage


class DashboardPage(BasePage):
    """Page Object for the Dashboard page containing rosbag controls"""

    # Rosbag Control Selectors
    ROSBAG_INDICATOR = "#rosbagIndicator"
    ROSBAG_STATUS_TEXT = "#rosbagStatusText"
    ROSBAG_INFO_DIV = "#rosbagInfo"
    ROSBAG_FILE = "#rosbagFile"
    ROSBAG_DURATION = "#rosbagDuration"
    ROSBAG_TOPIC_COUNT = "#rosbagTopicCount"
    START_BUTTON = "#startRosbagBtn"
    STOP_BUTTON = "#stopRosbagBtn"
    REFRESH_BUTTON = "#rosbagRefreshBtn"
    ROSBAG_CARD = "#rosbagCard"

    def __init__(self, page: Page, base_url: str = "http://localhost:5000"):
        super().__init__(page, base_url)

    def navigate_to_dashboard(self) -> None:
        """Navigate to the dashboard page"""
        self.navigate("/")

    # ==================== State Query Methods ====================

    def get_rosbag_indicator_class(self) -> str:
        """Get the CSS class of the rosbag status indicator"""
        element = self.page.locator(self.ROSBAG_INDICATOR)
        return element.get_attribute("class") or ""

    def get_rosbag_status_text(self) -> str:
        """Get the rosbag status text"""
        return self.get_text(self.ROSBAG_STATUS_TEXT)

    def is_rosbag_info_visible(self) -> bool:
        """Check if rosbag info section is visible"""
        return self.is_visible(self.ROSBAG_INFO_DIV, timeout=1000)

    def get_rosbag_file(self) -> str:
        """Get the current rosbag file path"""
        return self.get_text(self.ROSBAG_FILE)

    def get_rosbag_duration(self) -> str:
        """Get the rosbag recording duration"""
        return self.get_text(self.ROSBAG_DURATION)

    def get_rosbag_topic_count(self) -> int:
        """Get the number of topics being recorded"""
        text = self.get_text(self.ROSBAG_TOPIC_COUNT)
        try:
            return int(text)
        except (ValueError, TypeError):
            return 0

    def is_start_button_enabled(self) -> bool:
        """Check if start button is enabled"""
        return self.is_enabled(self.START_BUTTON)

    def is_start_button_disabled(self) -> bool:
        """Check if start button is disabled"""
        return self.is_disabled(self.START_BUTTON)

    def is_stop_button_enabled(self) -> bool:
        """Check if stop button is enabled"""
        return self.is_enabled(self.STOP_BUTTON)

    def is_stop_button_disabled(self) -> bool:
        """Check if stop button is disabled"""
        return self.is_disabled(self.STOP_BUTTON)

    # ==================== Action Methods ====================

    def click_start_button(self) -> None:
        """Click the start recording button"""
        self.click_element(self.START_BUTTON)

    def click_stop_button(self) -> None:
        """Click the stop recording button"""
        self.click_element(self.STOP_BUTTON)

    def click_refresh_button(self) -> None:
        """Click the refresh button"""
        self.click_element(self.REFRESH_BUTTON)

    # ==================== Wait Methods ====================

    def wait_for_recording_state(self, timeout: int = 10000) -> None:
        """Wait for the UI to show recording state"""
        self.page.wait_for_function(
            """() => {
                const indicator = document.getElementById('rosbagIndicator');
                const statusText = document.getElementById('rosbagStatusText');
                return indicator && indicator.classList.contains('recording') &&
                       statusText && statusText.textContent === 'Recording';
            }""",
            timeout=timeout
        )

    def wait_for_idle_state(self, timeout: int = 10000) -> None:
        """Wait for the UI to show idle state"""
        self.page.wait_for_function(
            """() => {
                const indicator = document.getElementById('rosbagIndicator');
                const statusText = document.getElementById('rosbagStatusText');
                return indicator && indicator.classList.contains('idle') &&
                       statusText && statusText.textContent === 'Idle';
            }""",
            timeout=timeout
        )

    def wait_for_status_text(self, text: str, timeout: int = 5000) -> None:
        """Wait for status text to match expected value"""
        element = self.page.locator(self.ROSBAG_STATUS_TEXT)

        def text_matches():
            return element.text_content() == text

        self.page.wait_for_function(text_matches, timeout=timeout)

    def wait_for_start_button_enabled(self, timeout: int = 5000) -> None:
        """Wait for start button to be enabled"""
        element = self.page.locator(self.START_BUTTON)

        def is_enabled():
            return not element.is_disabled()

        self.page.wait_for_function(is_enabled, timeout=timeout)

    def wait_for_start_button_disabled(self, timeout: int = 5000) -> None:
        """Wait for start button to be disabled"""
        element = self.page.locator(self.START_BUTTON)

        def is_disabled():
            return element.is_disabled()

        self.page.wait_for_function(is_disabled, timeout=timeout)

    def wait_for_stop_button_enabled(self, timeout: int = 5000) -> None:
        """Wait for stop button to be enabled"""
        element = self.page.locator(self.STOP_BUTTON)

        def is_enabled():
            return not element.is_disabled()

        self.page.wait_for_function(is_enabled, timeout=timeout)

    def wait_for_stop_button_disabled(self, timeout: int = 5000) -> None:
        """Wait for stop button to be disabled"""
        element = self.page.locator(self.STOP_BUTTON)

        def is_disabled():
            return element.is_disabled()

        self.page.wait_for_function(is_disabled, timeout=timeout)

    # ==================== State Summary Methods ====================

    def get_rosbag_state(self) -> Dict[str, Any]:
        """Get complete rosbag state from UI"""
        return {
            "status_text": self.get_rosbag_status_text(),
            "indicator_class": self.get_rosbag_indicator_class(),
            "info_visible": self.is_rosbag_info_visible(),
            "file": self.get_rosbag_file() if self.is_rosbag_info_visible() else None,
            "duration": self.get_rosbag_duration() if self.is_rosbag_info_visible() else None,
            "topic_count": self.get_rosbag_topic_count() if self.is_rosbag_info_visible() else 0,
            "start_enabled": self.is_start_button_enabled(),
            "stop_enabled": self.is_stop_button_enabled()
        }

    # ==================== Utility Methods ====================

    def parse_duration_to_seconds(self, duration: str) -> int:
        """Parse duration string (MM:SS) to seconds"""
        match = re.match(r'(\d+):(\d+)', duration)
        if match:
            minutes, seconds = match.groups()
            return int(minutes) * 60 + int(seconds)
        return 0

    def wait_for_duration_update(self, initial_duration: str, timeout: int = 5000) -> str:
        """Wait for duration to increment (indicating active recording)"""
        element = self.page.locator(self.ROSBAG_DURATION)

        def duration_increased():
            current = element.text_content()
            return current != initial_duration and current != "--:--"

        self.page.wait_for_function(duration_increased, timeout=timeout)
        return element.text_content()

    def get_start_button_html(self) -> str:
        """Get the HTML content of the start button (for checking loading state)"""
        return self.get_html(self.START_BUTTON)

    def get_stop_button_html(self) -> str:
        """Get the HTML content of the stop button (for checking loading state)"""
        return self.get_html(self.STOP_BUTTON)

    def is_start_button_loading(self) -> bool:
        """Check if start button is in loading state"""
        html = self.get_start_button_html()
        return "fa-spin" in html or "Starting" in html

    def is_stop_button_loading(self) -> bool:
        """Check if stop button is in loading state"""
        html = self.get_stop_button_html()
        return "fa-spin" in html or "Stopping" in html

    # ==================== Card Methods ====================

    def is_rosbag_card_present(self) -> bool:
        """Check if rosbag card is present on the page"""
        return self.is_visible(self.ROSBAG_CARD)

    def is_rosbag_card_visible(self) -> bool:
        """Check if rosbag card is visible"""
        return self.is_visible(self.ROSBAG_CARD)

    # ==================== Refresh Button Methods ====================

    def is_refresh_button_spinning(self) -> bool:
        """Check if refresh button icon is spinning"""
        element = self.page.locator(f"{self.REFRESH_BUTTON} i")
        classes = element.get_attribute("class") or ""
        return "fa-spin" in classes

    def wait_for_refresh_spin(self, timeout: int = 3000) -> None:
        """Wait for refresh button to spin (animation)"""
        element = self.page.locator(f"{self.REFRESH_BUTTON} i")

        def is_spinning():
            classes = element.get_attribute("class") or ""
            return "fa-spin" in classes

        self.page.wait_for_function(is_spinning, timeout=timeout)

    def wait_for_refresh_stop_spin(self, timeout: int = 3000) -> None:
        """Wait for refresh button to stop spinning"""
        element = self.page.locator(f"{self.REFRESH_BUTTON} i")

        def not_spinning():
            classes = element.get_attribute("class") or ""
            return "fa-spin" not in classes

        self.page.wait_for_function(not_spinning, timeout=timeout)
