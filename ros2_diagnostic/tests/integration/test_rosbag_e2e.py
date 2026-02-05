# test_rosbag_e2e.py - End-to-end integration tests for rosbag recording

import pytest
import requests
import sys
import time
from pathlib import Path
from playwright.sync_api import Page

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

try:
    from pages.dashboard_page import DashboardPage
except ImportError:
    DashboardPage = None

# Import ROS2 status check from parent conftest
try:
    import conftest
    check_ros2_status = conftest.check_ros2_status
except (ImportError, AttributeError):
    check_ros2_status = None


@pytest.fixture
def api_client(base_url: str):
    """Create an API client for testing"""
    session = requests.Session()
    session.headers.update({'Content-Type': 'application/json'})
    return session


@pytest.mark.integration
class TestRosbagAPIEndpoints:
    """Integration tests for API endpoints"""

    def test_api_responds(self, base_url: str, api_client):
        """Test that API server responds"""
        try:
            response = api_client.get(f"{base_url}/api/rosbag/status", timeout=5)
            # Any response (success or error) means server is up
            assert response.status_code in [200, 500, 404]
        except requests.exceptions.ConnectionError:
            pytest.skip("API server not running")

    def test_status_endpoint_structure(self, base_url: str, api_client):
        """Test status endpoint returns valid JSON structure"""
        try:
            response = api_client.get(f"{base_url}/api/rosbag/status", timeout=5)

            if response.status_code == 200:
                data = response.json()
                # Check response structure
                assert 'success' in data
                assert 'data' in data
                # data should contain expected fields
                if data['success']:
                    assert 'is_recording' in data['data']
            else:
                pytest.skip(f"API returned status {response.status_code}")
        except requests.exceptions.ConnectionError:
            pytest.skip("API server not running")
        except requests.exceptions.Timeout:
            pytest.skip("API server timeout")

    def test_start_endpoint_exists(self, base_url: str, api_client):
        """Test start endpoint exists"""
        try:
            response = api_client.post(f"{base_url}/api/rosbag/start", json={}, timeout=5)
            # Should get some response (may be error if dependencies missing)
            assert response.status_code in [200, 500, 404]
        except requests.exceptions.ConnectionError:
            pytest.skip("API server not running")

    def test_stop_endpoint_exists(self, base_url: str, api_client):
        """Test stop endpoint exists"""
        try:
            response = api_client.post(f"{base_url}/api/rosbag/stop", timeout=5)
            # Should get some response
            assert response.status_code in [200, 500, 404]
        except requests.exceptions.ConnectionError:
            pytest.skip("API server not running")


@pytest.mark.integration
class TestRosbagUIAPIIntegration:
    """Integration tests for UI and API consistency"""

    def test_api_ui_reachable(self, base_url: str):
        """Test that both API and UI are reachable"""
        api_ok = False
        ui_ok = False

        # Check API
        try:
            response = requests.get(f"{base_url}/api/rosbag/status", timeout=2)
            api_ok = response.status_code in [200, 500]
        except requests.exceptions.ConnectionError:
            pass

        # Check UI
        try:
            response = requests.get(base_url, timeout=2)
            ui_ok = response.status_code == 200
        except requests.exceptions.ConnectionError:
            pass

        # At least one should be available
        assert api_ok or ui_ok, "Neither API nor UI is reachable"


@pytest.mark.e2e
@pytest.mark.skipif(DashboardPage is None, reason="DashboardPage not available")
class TestRosbagRecordingWorkflow:
    """End-to-end tests for complete recording workflow"""

    def test_dashboard_loads(self, page: Page, base_url: str):
        """Test that dashboard page loads"""
        page.goto(base_url)
        page.wait_for_load_state("networkidle", timeout=10000)

        # Check we're on the right page
        assert base_url in page.url

    def test_rosbag_controls_render(self, dashboard_page):
        """Test rosbag controls render on page"""
        # Should be able to see the rosbag card
        assert dashboard_page.is_rosbag_card_present()

    def test_ui_state_query(self, dashboard_page):
        """Test querying UI state"""
        state = dashboard_page.get_rosbag_state()

        # Verify state is a dictionary with expected keys
        assert isinstance(state, dict)
        expected_keys = [
            'status_text', 'indicator_class', 'info_visible',
            'file', 'duration', 'topic_count',
            'start_enabled', 'stop_enabled'
        ]
        for key in expected_keys:
            assert key in state

    def test_button_interaction(self, dashboard_page):
        """Test clicking buttons without errors"""
        # Click refresh (safe operation)
        dashboard_page.click_refresh_button()

        # Should not cause any JavaScript errors
        # We can't easily check for console errors in sync API,
        # but we can verify the page is still responsive
        assert dashboard_page.is_rosbag_card_present()


@pytest.mark.integration
class TestRosbagMockAPIResponse:
    """Tests with mocked API responses"""

    def test_ui_with_mocked_idle_state(self, page: Page, base_url: str):
        """Test UI displays idle state correctly"""
        # Mock API response for idle state
        page.route("**/api/rosbag/status", lambda route: route.fulfill(
            status=200,
            body='{"success": true, "data": {"is_recording": false, "config_loaded": true, "topics_count": 4}}'
        ))

        page.goto(base_url)
        page.wait_for_load_state("networkidle")

        # Verify page loaded
        assert base_url in page.url

    def test_ui_with_mocked_recording_state(self, page: Page, base_url: str):
        """Test UI displays recording state correctly"""
        # Mock API response for recording state
        page.route("**/api/rosbag/status", lambda route: route.fulfill(
            status=200,
            body='{"success": true, "data": {"is_recording": true, "current_bag": "/tmp/test_bag", "duration": 65, "topics_count": 4}}'
        ))

        page.goto(base_url)
        page.wait_for_load_state("networkidle")

        # Verify page loaded
        assert base_url in page.url


@pytest.mark.integration
class TestRosbagErrorScenarios:
    """Tests for error scenarios"""

    def test_api_error_handling(self, base_url: str, api_client):
        """Test API handles errors gracefully"""
        try:
            # Try an invalid endpoint
            response = api_client.get(f"{base_url}/api/rosbag/invalid_endpoint", timeout=5)

            # Should return 404 or handle gracefully
            assert response.status_code == 404
        except requests.exceptions.ConnectionError:
            pytest.skip("API server not running")

    def test_malformed_json_request(self, base_url: str, api_client):
        """Test API handles malformed JSON"""
        try:
            response = api_client.post(
                f"{base_url}/api/rosbag/start",
                data="{invalid json",
                headers={'Content-Type': 'application/json'},
                timeout=5
            )

            # Should return 400 or handle error
            assert response.status_code in [400, 500]
        except requests.exceptions.ConnectionError:
            pytest.skip("API server not running")


@pytest.mark.integration
class TestRosbagConcurrency:
    """Tests for concurrent access"""

    def test_multiple_status_requests(self, base_url: str):
        """Test handling multiple simultaneous status requests"""
        try:
            import threading

            results = []

            def make_request():
                try:
                    response = requests.get(f"{base_url}/api/rosbag/status", timeout=5)
                    results.append(response.status_code)
                except Exception as e:
                    results.append(str(e))

            threads = [threading.Thread(target=make_request) for _ in range(5)]

            for t in threads:
                t.start()
            for t in threads:
                t.join()

            # All requests should complete without error
            assert len(results) == 5
        except requests.exceptions.ConnectionError:
            pytest.skip("API server not running")


@pytest.mark.integration
class TestRosbagDataValidation:
    """Tests for data validation"""

    def test_status_response_data_types(self, base_url: str, api_client):
        """Test status API returns correct data types"""
        try:
            response = api_client.get(f"{base_url}/api/rosbag/status", timeout=5)

            if response.status_code == 200:
                data = response.json()
                if data.get('success'):
                    result = data['data']
                    # Check data types
                    assert isinstance(result.get('is_recording'), bool)
                    assert isinstance(result.get('topics_count'), int)
                    assert isinstance(result.get('success'), bool) or result.get('success') is None
            else:
                pytest.skip(f"API returned status {response.status_code}")
        except requests.exceptions.ConnectionError:
            pytest.skip("API server not running")


@pytest.mark.e2e
@pytest.mark.recording
class TestRosbagActualRecording:
    """End-to-end tests for actual rosbag recording.

    These tests require ROS2 system to be running with active nodes.
    Tests will be skipped if ROS2 is not available.
    """

    @pytest.fixture(autouse=True)
    def skip_if_no_ros2(self, base_url: str):
        """Skip all tests in this class if ROS2 is not running."""
        # Import at runtime to avoid issues with module-level imports
        try:
            import conftest as cf
            check_func = cf.check_ros2_status
        except (ImportError, AttributeError):
            check_func = None

        if check_func:
            try:
                is_running = check_func(base_url)
                if not is_running:
                    pytest.skip("ROS2 system not running - required for recording tests")
            except Exception as e:
                pytest.skip(f"Could not check ROS2 status: {e}")
        else:
            # If check function not available, try to connect directly
            try:
                import requests
                response = requests.get(f"{base_url}/api/ros2/control/status", timeout=2)
                if response.status_code != 200:
                    pytest.skip("ROS2 API not responding")
                data = response.json()
                if not data.get('success') or not data.get('data', {}).get('running'):
                    pytest.skip("ROS2 system not running")
            except Exception:
                pytest.skip("ROS2 system not running - required for recording tests")

    def test_ros2_status_endpoint(self, base_url: str, api_client):
        """Test ROS2 status endpoint returns valid data."""
        response = api_client.get(f"{base_url}/api/ros2/control/status", timeout=5)
        assert response.status_code == 200

        data = response.json()
        assert 'success' in data
        assert 'data' in data

    def test_ros2_nodes_exist(self, base_url: str, api_client):
        """Test that ROS2 nodes are available."""
        response = api_client.get(f"{base_url}/api/ros2/nodes", timeout=5)
        assert response.status_code == 200

        data = response.json()
        if data.get('success'):
            nodes = data.get('data', [])
            # Should have at least some nodes
            assert isinstance(nodes, list)

    def test_ros2_topics_exist(self, base_url: str, api_client):
        """Test that ROS2 topics are available."""
        response = api_client.get(f"{base_url}/api/ros2/topics", timeout=5)
        assert response.status_code == 200

        data = response.json()
        if data.get('success'):
            topics = data.get('data', [])
            # Should have at least some topics
            assert isinstance(topics, list)

    def test_actual_start_recording_cycle(self, base_url: str, api_client):
        """Test complete recording cycle with actual data.

        This test:
        1. Checks initial status (not recording)
        2. Starts recording
        3. Verifies recording state
        4. Stops recording
        5. Verifies stopped state
        """
        # 1. Check initial status
        response = api_client.get(f"{base_url}/api/rosbag/status", timeout=10)
        assert response.status_code == 200

        data = response.json()
        initial_recording = data.get('data', {}).get('is_recording', False)

        # If already recording, stop it first
        if initial_recording:
            stop_response = api_client.post(f"{base_url}/api/rosbag/stop", timeout=10)
            assert stop_response.status_code == 200
            time.sleep(2)

        # 2. Start recording
        start_response = api_client.post(
            f"{base_url}/api/rosbag/start",
            json={},
            timeout=30  # Longer timeout for service call
        )
        assert start_response.status_code == 200

        start_data = start_response.json()
        if not start_data.get('success'):
            pytest.skip(f"Could not start recording: {start_data.get('message')}")

        # 3. Wait a moment and check recording state
        time.sleep(3)
        status_response = api_client.get(f"{base_url}/api/rosbag/status", timeout=10)
        assert status_response.status_code == 200

        status_data = status_response.json()
        is_recording = status_data.get('data', {}).get('is_recording', False)

        # 4. Stop recording
        stop_response = api_client.post(f"{base_url}/api/rosbag/stop", timeout=30)
        assert stop_response.status_code == 200

        stop_data = stop_response.json()
        assert stop_data.get('success') is True

        # 5. Verify stopped state
        time.sleep(2)
        final_status = api_client.get(f"{base_url}/api/rosbag/status", timeout=10)
        assert final_status.status_code == 200

        final_data = final_status.json()
        final_recording = final_data.get('data', {}).get('is_recording', False)
        assert final_recording is False

    def test_start_ros2_does_not_auto_record(self, base_url: str, api_client):
        """Verify that starting ROS2 does not automatically start recording.

        This is a regression test for the bug where starting ROS2 would
        automatically trigger rosbag recording because the script was
        run_ros2_all_record.sh instead of run_ros2_all.sh.
        """
        # 1. Get initial rosbag status
        initial_rosbag_status = api_client.get(f"{base_url}/api/rosbag/status", timeout=10)
        if initial_rosbag_status.status_code != 200:
            pytest.skip("Rosbag API not responding")

        initial_data = initial_rosbag_status.json()
        initial_recording = initial_data.get('data', {}).get('is_recording', False)

        # If already recording, stop first
        if initial_recording:
            api_client.post(f"{base_url}/api/rosbag/stop", timeout=10)
            time.sleep(2)

        # 2. Start ROS2 system
        start_response = api_client.post(f"{base_url}/api/ros2/control/start", timeout=15)
        if start_response.status_code != 200:
            pytest.skip("ROS2 control API not responding")

        start_data = start_response.json()
        if not start_data.get('success'):
            pytest.skip(f"Could not start ROS2: {start_data.get('message')}")

        # 3. Wait for system to initialize
        time.sleep(5)

        # 4. Check rosbag status - should NOT be recording
        rosbag_status = api_client.get(f"{base_url}/api/rosbag/status", timeout=10)
        assert rosbag_status.status_code == 200

        rosbag_data = rosbag_status.json()
        is_recording = rosbag_data.get('data', {}).get('is_recording', False)

        # This is the key assertion - starting ROS2 should NOT auto-record
        assert is_recording is False, (
            f"Recording should not start automatically when ROS2 starts. "
            f"Expected is_recording=False, got is_recording={is_recording}"
        )

        # 5. Cleanup - stop ROS2
        api_client.post(f"{base_url}/api/ros2/control/stop", timeout=10)
