# conftest.py - Playwright fixtures for UI tests

import pytest
from playwright.sync_api import Browser, BrowserContext, Page


@pytest.fixture(scope="session")
def browser_context_args(browser_context_args):
    """Configure browser context for testing"""
    return {
        **browser_context_args,
        "viewport": {"width": 1920, "height": 1080},
        "ignore_https_errors": True,
    }


@pytest.fixture
def dashboard_page(page: Page, base_url: str):
    """Navigate to dashboard and return page object"""
    from pages.dashboard_page import DashboardPage

    dashboard = DashboardPage(page, base_url)
    dashboard.navigate_to_dashboard()

    # Wait for page to load completely
    page.wait_for_load_state("networkidle")

    # Wait for rosbag card to be present
    try:
        page.wait_for_selector("#rosbagIndicator", timeout=5000)
    except Exception:
        pass

    return dashboard
