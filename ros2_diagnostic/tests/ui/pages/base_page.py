# base_page.py - Base page class with common functionality

from playwright.sync_api import Page, Locator, TimeoutError as PlaywrightTimeout
import logging
import re
from typing import Any, Optional

logger = logging.getLogger(__name__)


class BasePage:
    """Base page class with common functionality for all pages"""

    def __init__(self, page: Page, base_url: str = "http://localhost:8000"):
        self.page = page
        self.base_url = base_url
        self.timeout = 5000  # Default timeout in ms

    def navigate(self, path: str = "/") -> None:
        """Navigate to a specific path"""
        url = f"{self.base_url}{path}"
        logger.info(f"Navigating to: {url}")
        self.page.goto(url)
        self.page.wait_for_load_state("networkidle")

    def wait_for_selector(self, selector: str, timeout: int = None) -> Locator:
        """Wait for an element to be present and return it"""
        timeout = timeout or self.timeout
        try:
            return self.page.wait_for_selector(selector, timeout=timeout)
        except PlaywrightTimeout as e:
            logger.error(f"Element not found: {selector}")
            raise

    def click_element(self, selector: str, timeout: int = None) -> None:
        """Click an element with error handling"""
        element = self.wait_for_selector(selector, timeout)
        element.click()

    def fill_text(self, selector: str, text: str, timeout: int = None) -> None:
        """Fill text into an input field"""
        element = self.wait_for_selector(selector, timeout)
        element.fill(text)

    def get_text(self, selector: str, timeout: int = None) -> str:
        """Get text content of an element"""
        timeout = timeout or self.timeout
        element = self.page.locator(selector)
        element.wait_for(state="visible", timeout=timeout)
        return element.text_content()

    def get_inner_text(self, selector: str, timeout: int = None) -> str:
        """Get inner text of an element"""
        timeout = timeout or self.timeout
        element = self.page.locator(selector)
        element.wait_for(state="visible", timeout=timeout)
        return element.inner_text()

    def is_visible(self, selector: str, timeout: int = 1000) -> bool:
        """Check if an element is visible"""
        try:
            self.page.wait_for_selector(selector, timeout=timeout, state="visible")
            return True
        except PlaywrightTimeout:
            return False

    def is_enabled(self, selector: str) -> bool:
        """Check if a button is enabled"""
        element = self.page.locator(selector)
        return not element.is_disabled()

    def is_disabled(self, selector: str) -> bool:
        """Check if a button is disabled"""
        element = self.page.locator(selector)
        return element.is_disabled()

    def wait_for_text_change(self, selector: str, initial_text: str, timeout: int = None) -> str:
        """Wait for text content to change from initial value"""
        timeout = timeout or self.timeout
        element = self.page.locator(selector)

        def text_changed():
            current_text = element.text_content()
            return current_text != initial_text

        self.page.wait_for_function(text_changed, timeout=timeout)
        return element.text_content()

    def get_attribute(self, selector: str, attribute: str) -> Optional[str]:
        """Get attribute value of an element"""
        element = self.page.locator(selector)
        return element.get_attribute(attribute)

    def has_class(self, selector: str, class_name: str) -> bool:
        """Check if an element has a specific CSS class"""
        element = self.page.locator(selector)
        classes = element.get_attribute("class") or ""
        return class_name in classes.split()

    def wait_for_class_contains(self, selector: str, class_name: str, timeout: int = None) -> None:
        """Wait for an element to contain a specific CSS class"""
        timeout = timeout or self.timeout
        element = self.page.locator(selector)

        def has_class():
            classes = element.get_attribute("class") or ""
            return class_name in classes.split()

        self.page.wait_for_function(has_class, timeout=timeout)

    def wait_for_hidden(self, selector: str, timeout: int = None) -> None:
        """Wait for an element to become hidden"""
        timeout = timeout or self.timeout
        self.page.wait_for_selector(selector, state="hidden", timeout=timeout)

    def get_html(self, selector: str, timeout: int = None) -> str:
        """Get inner HTML of an element"""
        timeout = timeout or self.timeout
        element = self.page.locator(selector)
        element.wait_for(state="visible", timeout=timeout)
        return element.inner_html()

    def count_elements(self, selector: str) -> int:
        """Count the number of elements matching the selector"""
        return self.page.locator(selector).count()

    def evaluate_script(self, script: str) -> Any:
        """Execute JavaScript in the page context"""
        return self.page.evaluate(script)

    def wait_for_url_contains(self, fragment: str, timeout: int = None) -> None:
        """Wait for URL to contain a specific fragment"""
        timeout = timeout or self.timeout
        self.page.wait_for_url(f"**/*{fragment}*", timeout=timeout)

    def reload(self) -> None:
        """Reload the current page"""
        self.page.reload()
        self.page.wait_for_load_state("networkidle")

    def go_back(self) -> None:
        """Navigate back in browser history"""
        self.page.go_back()
        self.page.wait_for_load_state("networkidle")

    def screenshot(self, path: str) -> None:
        """Take a screenshot of the current page"""
        self.page.screenshot(path=path)

    def get_console_messages(self) -> list:
        """Get all console messages"""
        # This would need to be set up before page load
        return []

    def click_by_text(self, text: str, exact: bool = True) -> None:
        """Click an element by its text content"""
        if exact:
            self.page.get_by_text(text, exact=True).click()
        else:
            self.page.get_by_text(text, exact=False).click()

    def click_by_role(self, role: str, name: str = None) -> None:
        """Click an element by its ARIA role"""
        if name:
            self.page.get_by_role(role, name=name).click()
        else:
            self.page.get_by_role(role).first.click()

    def get_element_text_by_role(self, role: str, name: str = None) -> str:
        """Get text content of an element by its ARIA role"""
        if name:
            return self.page.get_by_role(role, name=name).text_content()
        return self.page.get_by_role(role).first.text_content()
