# sensors_page.py - Page object for the sensor diagnostics page

from typing import Dict

from tests.ui.pages.base_page import BasePage


class SensorsPage(BasePage):
    """Page object for sensor diagnostics interactions."""

    PI5_TAB = 'button[data-sensor="pi5_sensors"]'
    PI5_PANEL = '#pi5_sensorsPanel'
    PI5_STATUS_BADGE = '#pi5SensorsStatusBadge'
    PI5_NETWORK_STATUS = '#pi5NetworkStatus'
    PI5_DATA_AGE = '#pi5DataAge'
    PI5_C4E_TEMP = '#pi5C4eTemp'
    PI5_CONDUCTIVITY = '#pi5Conductivity'
    PI5_PH = '#pi5Ph'
    PI5_REDOX = '#pi5Redox'
    PI5_UPS_COMPONENT = '#pi5UpsComponent'
    PI5_UPS_PARAMETER = '#pi5UpsParameter'
    PI5_UPS_VALUE = '#pi5UpsValue'
    PI5_UPS_STATE = '#pi5UpsState'

    def navigate_to_pi5_sensors(self) -> None:
        """Open the sensors page with the Pi5 tab selected."""
        self.navigate('/sensors?sensor=pi5_sensors')

    def wait_for_pi5_panel_active(self, timeout: int = 5000) -> None:
        """Wait until the Pi5 panel is the active visible panel."""
        self.page.wait_for_function(
            """() => {
                const tab = document.querySelector('button[data-sensor="pi5_sensors"]');
                const panel = document.getElementById('pi5_sensorsPanel');
                return tab && panel &&
                    tab.classList.contains('active') &&
                    panel.classList.contains('active');
            }""",
            timeout=timeout,
        )

    def wait_for_pi5_values(self, timeout: int = 15000) -> None:
        """Wait until Pi5 values from MQTT are rendered in the DOM."""
        self.page.wait_for_function(
            """() => {
                const badge = document.getElementById('pi5SensorsStatusBadge');
                const network = document.getElementById('pi5NetworkStatus');
                const age = document.getElementById('pi5DataAge');
                const ph = document.getElementById('pi5Ph');
                const conductivity = document.getElementById('pi5Conductivity');
                return badge && network && age && ph && conductivity &&
                    badge.textContent.trim() === 'OK' &&
                    network.textContent.trim() === 'Online' &&
                    age.textContent.trim() === 'Active' &&
                    ph.textContent.trim() !== '--' &&
                    conductivity.textContent.trim() !== '-- µS/cm';
            }""",
            timeout=timeout,
        )

    def get_pi5_snapshot(self) -> Dict[str, str]:
        """Return the Pi5 panel values currently shown on the page."""
        return {
            'status': self.get_text(self.PI5_STATUS_BADGE).strip(),
            'network': self.get_text(self.PI5_NETWORK_STATUS).strip(),
            'data_age': self.get_text(self.PI5_DATA_AGE).strip(),
            'c4e_temp': self.get_text(self.PI5_C4E_TEMP).strip(),
            'conductivity': self.get_text(self.PI5_CONDUCTIVITY).strip(),
            'ph': self.get_text(self.PI5_PH).strip(),
            'redox': self.get_text(self.PI5_REDOX).strip(),
            'ups_component': self.get_text(self.PI5_UPS_COMPONENT).strip(),
            'ups_parameter': self.get_text(self.PI5_UPS_PARAMETER).strip(),
            'ups_value': self.get_text(self.PI5_UPS_VALUE).strip(),
            'ups_state': self.get_text(self.PI5_UPS_STATE).strip(),
        }
