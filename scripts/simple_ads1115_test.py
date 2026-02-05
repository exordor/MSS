#!/usr/bin/env python3
"""
Simplified ADS1115 Continuous Monitoring Script - Single-Ended Measurement
Reads all 4 channels (A0, A1, A2, A3) separately

Channel configuration:
- Channel 0: A0 (Messtechnik +)
- Channel 1: A1 (Messtechnik -)
- Channel 2: A2 (Antrieb +)
- Channel 3: A3 (Antrieb -)

"""
import signal
import sys
import time
from datetime import datetime
from smbus2 import SMBus


class ADS1115:
    """Simplified ADS1115 class supporting single-ended and differential measurements"""

    # MUX configuration (per ADS1115 datasheet)
    # Differential mode:
    #   0x0000 = A0 - A1
    #   0x1000 = A0 - A3
    #   0x2000 = A1 - A3
    #   0x3000 = A2 - A3
    # Single-ended mode:
    #   0x4000 = A0 - GND
    #   0x5000 = A1 - GND
    #   0x6000 = A2 - GND
    #   0x7000 = A3 - GND

    MUX_DIFF = {
        0: 0x0000,  # A0 - A1
        1: 0x3000,  # A2 - A3
    }

    MUX_SINGLE = {
        0: 0x4000,  # A0 - GND
        1: 0x5000,  # A1 - GND
        2: 0x6000,  # A2 - GND
        3: 0x7000,  # A3 - GND
    }

    # PGA configuration (gain and full-scale voltage)
    PGA_CONFIG = {
        2/3: (0x0000, 6.144),  # +/-6.144V
        1:   (0x0200, 4.096),  # +/-4.096V
        2:   (0x0400, 2.048),  # +/-2.048V
        4:   (0x0600, 1.024),  # +/-1.024V
        8:   (0x0800, 0.512),  # +/-0.512V
    }

    def __init__(self, bus_num=1, addr=0x48, gain=1):
        """
        Initialize ADS1115

        Args:
            bus_num: I2C bus number
            addr: I2C address
            gain: PGA gain (1 = +/-4.096V, 2 = +/-2.048V, etc.)
        """
        self.bus = SMBus(bus_num)
        self.addr = addr
        self.gain = gain
        self._pga_config, self.fullscale_voltage = self.PGA_CONFIG[gain]

    def read_differential(self, channel):
        """
        Read differential channel

        Args:
            channel: 0 = A0-A1, 1 = A2-A3

        Returns:
            Differential voltage (Vdiff = V+ - V-)
        """
        if channel not in self.MUX_DIFF:
            raise ValueError(f"Unsupported differential channel: {channel}")

        mux = self.MUX_DIFF[channel]

        # Config: OS_SINGLE | MUX | PGA | MODE_SINGLE | 860SPS | COMP_DISABLED
        config = 0x8000 | mux | self._pga_config | 0x0100 | 0x00E0 | 0x0003

        # Write config
        self.bus.write_i2c_block_data(self.addr, 0x01, [(config >> 8) & 0xFF, config & 0xFF])
        time.sleep(0.002)  # Wait for conversion (~1.2ms @ 860SPS)

        # Read conversion
        data = self.bus.read_i2c_block_data(self.addr, 0x00, 2)
        raw = (data[0] << 8) | data[1]

        # Signed conversion
        if raw & 0x8000:
            raw -= 0x10000

        # Convert to voltage
        return raw * self.fullscale_voltage / 32768.0

    def read_single(self, pin):
        """
        Read single-ended channel

        Args:
            pin: 0=A0, 1=A1, 2=A2, 3=A3

        Returns:
            Single-ended voltage (relative to GND)
        """
        if pin not in self.MUX_SINGLE:
            raise ValueError(f"Unsupported single-ended pin: {pin}")

        mux = self.MUX_SINGLE[pin]

        # Config: OS_SINGLE | MUX | PGA | MODE_SINGLE | 860SPS | COMP_DISABLED
        config = 0x8000 | mux | self._pga_config | 0x0100 | 0x00E0 | 0x0003

        # Write config
        self.bus.write_i2c_block_data(self.addr, 0x01, [(config >> 8) & 0xFF, config & 0xFF])
        time.sleep(0.002)

        # Read conversion
        data = self.bus.read_i2c_block_data(self.addr, 0x00, 2)
        raw = (data[0] << 8) | data[1]

        # Signed conversion
        if raw & 0x8000:
            raw -= 0x10000

        return raw * self.fullscale_voltage / 32768.0


def main():
    # Create ADS1115 instance (gain=1 = +/-4.096V, supports 3V full-scale)
    ads = ADS1115(gain=1)

    running = True

    def signal_handler(sig, frame):
        nonlocal running
        print("\n" + "=" * 100)
        running = False

    signal.signal(signal.SIGINT, signal_handler)

    print("=" * 100)
    print("  ADS1115 Single-Ended Measurement with Differential Calculation")
    print("=" * 100)
    print(f"  Mode: Single-Ended | PGA: +/-4.096V")
    print(f"  Messtechnik = A0 - A1 | Antrieb = A2 - A3")
    print("=" * 100)
    print(" Press Ctrl+C to stop")


    # Header
    print(f"\n{'Time':<10} {'A0(V)':<10} {'A1(V)':<10} {'A2(V)':<10} {'A3(V)':<10} {'Messtechnik(V)':<16} {'Antrieb(V)':<12}")
    print("-" * 100)

    prev_values = [0.0, 0.0, 0.0, 0.0]

    try:
        while running:
            timestamp = datetime.now().strftime('%H:%M:%S')

            # Read all 4 channels separately (single-ended)
            v_a0 = ads.read_single(0)  # A0
            v_a1 = ads.read_single(1)  # A1
            v_a2 = ads.read_single(2)  # A2
            v_a3 = ads.read_single(3)  # A3

            # Calculate differential voltages
            v_messtechnik = v_a0 - v_a1  # A0 - A1
            v_antrieb = v_a2 - v_a3       # A2 - A3

            # Detect changes and add markers
            marks = ["", "", "", ""]
            values = [v_a0, v_a1, v_a2, v_a3]
            for i in range(4):
                if abs(values[i] - prev_values[i]) > 0.01:
                    marks[i] = "^" if values[i] > prev_values[i] else "v"

            # Differential markers
            diff_marks = ["", ""]
            prev_diff = [prev_values[0] - prev_values[1], prev_values[2] - prev_values[3]]
            curr_diff = [v_messtechnik, v_antrieb]
            for i in range(2):
                if abs(curr_diff[i] - prev_diff[i]) > 0.01:
                    diff_marks[i] = "^" if curr_diff[i] > prev_diff[i] else "v"

            print(f"{timestamp:<10} {v_a0:>6.4f}{marks[0]:<3} {v_a1:>6.4f}{marks[1]:<3} "
                  f"{v_a2:>6.4f}{marks[2]:<3} {v_a3:>6.4f}{marks[3]:<3} "
                  f"{v_messtechnik:>7.4f}{diff_marks[0]:<3} {v_antrieb:>7.4f}{diff_marks[1]:<3}")

            prev_values = values
            time.sleep(0.2)

    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()
        return 1

    print("\nMonitoring ended")
    return 0


if __name__ == "__main__":
    sys.exit(main())
