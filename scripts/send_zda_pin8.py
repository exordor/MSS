#!/usr/bin/env python3
"""
Send NMEA time / GNSS-like sentences through the Jetson AGX Orin 40-pin header UART.

On the developer kit header, pin 8 is UART1_TX and pin 10 is UART1_RX.
This script only transmits, so connect:
  - Jetson pin 8  -> device RX
  - Jetson GND    -> device GND

In many JetPack setups the header UART is exposed as /dev/ttyTHS1. If your
board maps the header UART to a different device node, override it with
--port.

Important for SBG Ellipse:
  - Jetson header UART is 3.3V TTL.
  - Ellipse box units use RS-232/RS-422 serial levels, so a level shifter is
    required between Jetson pin 8 and the Ellipse serial input.
  - Direct wiring is only valid for Ellipse OEM variants that expose LvTTL
    serial pins.
  - SBG external NMEA aiding normally expects both serial NMEA and a 1 Hz PPS
    signal wired to a Sync input. This script only emulates the serial NMEA
    side.
"""

from __future__ import annotations

import argparse
import signal
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

try:
    import serial as _serial
except ImportError:
    _serial = None


DEFAULT_PORT = "/dev/ttyTHS1"
DEFAULT_BAUDRATE = 460800
DEFAULT_TALKER_ID = "GP"
DEFAULT_ZDA_RATE_HZ = 1.0
DEFAULT_SBG_RATE_HZ = 5.0
DEFAULT_FILE_REPLAY_SPEED = 1.0
DEFAULT_SIMULATED_LATITUDE = 52.5200
DEFAULT_SIMULATED_LONGITUDE = 13.4050
DEFAULT_SIMULATED_ALTITUDE_M = 35.0

_RUNNING = True


def resolve_pyserial():
    """Return the pyserial module or a human-readable error string."""
    if _serial is None:
        return None, (
            "pyserial is not installed. Fix with:\n"
            "  python -m pip install pyserial"
        )

    if hasattr(_serial, "Serial") and hasattr(_serial, "SerialException"):
        return _serial, None

    module_path = getattr(_serial, "__file__", "<unknown>")
    return None, (
        "imported the wrong 'serial' package instead of pyserial.\n"
        f"loaded module: {module_path}\n"
        "Fix with:\n"
        "  python -m pip uninstall -y serial\n"
        "  python -m pip install pyserial"
    )


def _handle_stop(_signum, _frame):
    global _RUNNING
    _RUNNING = False


def calculate_nmea_checksum(payload: str) -> str:
    """Return the NMEA XOR checksum for the payload without '$' or '*xx'."""
    checksum = 0
    for char in payload:
        checksum ^= ord(char)
    return f"{checksum:02X}"


def detect_local_zone_offset() -> tuple[int, int]:
    """Return the system local timezone offset as (hours, minutes)."""
    local_offset = datetime.now().astimezone().utcoffset()
    if local_offset is None:
        return 0, 0

    total_minutes = int(local_offset.total_seconds() // 60)
    sign = -1 if total_minutes < 0 else 1
    total_minutes = abs(total_minutes)
    return sign * (total_minutes // 60), total_minutes % 60


def normalize_zone_offset(
    zone_hours: int | None,
    zone_minutes: int | None,
) -> tuple[int, int]:
    """Resolve the effective local zone offset used in the ZDA sentence."""
    if zone_hours is None and zone_minutes is None:
        return detect_local_zone_offset()

    hours = zone_hours if zone_hours is not None else 0
    minutes = zone_minutes if zone_minutes is not None else 0

    if abs(hours) > 13:
        raise ValueError("local zone hours must be between -13 and +13")
    if abs(minutes) > 59:
        raise ValueError("local zone minutes must be between 0 and 59")

    sign = -1 if hours < 0 or minutes < 0 else 1
    return sign * abs(hours), abs(minutes)


def format_zone_hours(zone_hours: int) -> str:
    """Format the signed local zone hours field for ZDA."""
    if zone_hours < 0:
        return f"-{abs(zone_hours):02d}"
    return f"{zone_hours:02d}"


def format_time_hundredths(now_utc: datetime) -> str:
    hundredths = int(now_utc.microsecond / 10000)
    return now_utc.strftime("%H%M%S.") + f"{hundredths:02d}"


def format_nmea_float(value: float | None, digits: int) -> str:
    if value is None:
        return ""
    return f"{value:.{digits}f}"


def format_nmea_lat_lon(value: float | None, is_latitude: bool) -> tuple[str, str]:
    if value is None:
        return "", ""

    abs_value = abs(value)
    degrees = int(abs_value)
    minutes = (abs_value - degrees) * 60.0
    width = 2 if is_latitude else 3
    field = f"{degrees:0{width}d}{minutes:08.5f}"
    if is_latitude:
        hemisphere = "N" if value >= 0 else "S"
    else:
        hemisphere = "E" if value >= 0 else "W"
    return field, hemisphere


def build_nmea_sentence(talker_id: str, sentence_type: str, fields: list[str]) -> str:
    payload = ",".join([f"{talker_id}{sentence_type}", *fields])
    checksum = calculate_nmea_checksum(payload)
    return f"${payload}*{checksum}\r\n"


def build_zda_sentence(
    now_utc: datetime,
    talker_id: str,
    zone_hours: int,
    zone_minutes: int,
) -> str:
    """Build a complete NMEA ZDA sentence terminated with CRLF."""
    return build_nmea_sentence(
        talker_id=talker_id,
        sentence_type="ZDA",
        fields=[
            format_time_hundredths(now_utc),
            now_utc.strftime("%d"),
            now_utc.strftime("%m"),
            now_utc.strftime("%Y"),
            format_zone_hours(zone_hours),
            f"{zone_minutes:02d}",
        ],
    )


def build_rmc_sentence(
    now_utc: datetime,
    talker_id: str,
    latitude: float | None,
    longitude: float | None,
    speed_knots: float,
    course_deg: float,
    valid_fix: bool,
) -> str:
    lat_field, lat_hemi = format_nmea_lat_lon(latitude, is_latitude=True)
    lon_field, lon_hemi = format_nmea_lat_lon(longitude, is_latitude=False)
    status = "A" if valid_fix else "V"
    return build_nmea_sentence(
        talker_id=talker_id,
        sentence_type="RMC",
        fields=[
            format_time_hundredths(now_utc),
            status,
            lat_field,
            lat_hemi,
            lon_field,
            lon_hemi,
            format_nmea_float(speed_knots if valid_fix else 0.0, 2),
            format_nmea_float(course_deg if valid_fix else 0.0, 2),
            now_utc.strftime("%d%m%y"),
            "",
            "",
            "A" if valid_fix else "N",
        ],
    )


def build_gga_sentence(
    now_utc: datetime,
    talker_id: str,
    latitude: float | None,
    longitude: float | None,
    altitude_m: float | None,
    geoid_separation_m: float | None,
    fix_quality: int,
    num_satellites: int,
    hdop: float,
) -> str:
    lat_field, lat_hemi = format_nmea_lat_lon(latitude, is_latitude=True)
    lon_field, lon_hemi = format_nmea_lat_lon(longitude, is_latitude=False)
    valid_fix = fix_quality > 0 and latitude is not None and longitude is not None
    return build_nmea_sentence(
        talker_id=talker_id,
        sentence_type="GGA",
        fields=[
            format_time_hundredths(now_utc),
            lat_field,
            lat_hemi,
            lon_field,
            lon_hemi,
            str(fix_quality),
            f"{num_satellites:02d}",
            format_nmea_float(hdop, 1),
            format_nmea_float(altitude_m if valid_fix else None, 2),
            "M" if valid_fix and altitude_m is not None else "",
            format_nmea_float(geoid_separation_m if valid_fix else None, 2),
            "M" if valid_fix and geoid_separation_m is not None else "",
            "",
            "",
        ],
    )


def build_gst_sentence(
    now_utc: datetime,
    talker_id: str,
    gst_rms: float | None,
    gst_sigma_major: float | None,
    gst_sigma_minor: float | None,
    gst_orientation_deg: float | None,
    gst_sigma_lat: float | None,
    gst_sigma_lon: float | None,
    gst_sigma_alt: float | None,
) -> str:
    return build_nmea_sentence(
        talker_id=talker_id,
        sentence_type="GST",
        fields=[
            format_time_hundredths(now_utc),
            format_nmea_float(gst_rms, 2),
            format_nmea_float(gst_sigma_major, 2),
            format_nmea_float(gst_sigma_minor, 2),
            format_nmea_float(gst_orientation_deg, 1),
            format_nmea_float(gst_sigma_lat, 2),
            format_nmea_float(gst_sigma_lon, 2),
            format_nmea_float(gst_sigma_alt, 2),
        ],
    )


def build_hdt_sentence(talker_id: str, heading_deg: float) -> str:
    return build_nmea_sentence(
        talker_id=talker_id,
        sentence_type="HDT",
        fields=[format_nmea_float(heading_deg % 360.0, 2), "T"],
    )


def normalize_nmea_line(line: str) -> str:
    stripped = line.strip()
    if not stripped:
        return ""
    if not stripped.startswith("$"):
        raise ValueError(f"invalid NMEA line (missing '$'): {stripped}")
    return stripped + "\r\n"


def extract_nmea_time_seconds(sentence: str) -> float | None:
    fields = sentence.strip().split(",")
    if not fields:
        return None

    sentence_id = fields[0]
    if len(sentence_id) < 6:
        return None

    sentence_type = sentence_id[-3:]
    if sentence_type not in {"GGA", "GNS", "RMC", "GST", "ZDA"}:
        return None
    if len(fields) < 2 or not fields[1]:
        return None

    time_field = fields[1]
    if len(time_field) < 6:
        return None

    try:
        hours = int(time_field[0:2])
        minutes = int(time_field[2:4])
        seconds = float(time_field[4:])
    except ValueError:
        return None

    return hours * 3600 + minutes * 60 + seconds


def extract_nmea_sentence_type(sentence: str) -> str | None:
    fields = sentence.strip().split(",")
    if not fields:
        return None

    sentence_id = fields[0]
    if not sentence_id.startswith("$") or len(sentence_id) < 6:
        return None

    return sentence_id[-3:]


def extract_nmea_talker_id(sentence: str) -> str:
    sentence_id = sentence.strip().split(",", 1)[0]
    if sentence_id.startswith("$") and len(sentence_id) >= 3:
        return sentence_id[1:3]
    return DEFAULT_TALKER_ID


def parse_nmea_date(sentence: str) -> date | None:
    fields = sentence.strip().split(",")
    if not fields:
        return None

    sentence_type = extract_nmea_sentence_type(sentence)
    try:
        if sentence_type == "RMC" and len(fields) > 9 and fields[9]:
            day = int(fields[9][0:2])
            month = int(fields[9][2:4])
            year_two_digits = int(fields[9][4:6])
            year = 2000 + year_two_digits if year_two_digits < 80 else 1900 + year_two_digits
            return date(year, month, day)

        if sentence_type == "ZDA" and len(fields) > 4:
            day = int(fields[2])
            month = int(fields[3])
            year = int(fields[4])
            return date(year, month, day)
    except (ValueError, IndexError):
        return None

    return None


def combine_nmea_date_time(day: date, time_seconds: float) -> datetime:
    whole_seconds = int(time_seconds)
    fractional_seconds = time_seconds - whole_seconds
    hours, remainder = divmod(whole_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    microseconds = int(round(fractional_seconds * 1_000_000))

    if microseconds >= 1_000_000:
        seconds += 1
        microseconds -= 1_000_000
    if seconds >= 60:
        minutes += 1
        seconds -= 60
    if minutes >= 60:
        hours += 1
        minutes -= 60
    if hours >= 24:
        day = day + timedelta(days=hours // 24)
        hours %= 24

    return datetime(
        year=day.year,
        month=day.month,
        day=day.day,
        hour=hours,
        minute=minutes,
        second=seconds,
        microsecond=microseconds,
        tzinfo=timezone.utc,
    )


def load_nmea_file(path: str) -> list[str]:
    lines = []
    for raw_line in Path(path).read_text(encoding="ascii").splitlines():
        line = normalize_nmea_line(raw_line)
        if line:
            lines.append(line)

    if not lines:
        raise ValueError(f"no NMEA sentences found in {path}")

    return lines


def inject_missing_zda_sentences(
    sentences: list[str],
    zone_hours: int,
    zone_minutes: int,
) -> list[str]:
    output: list[str] = []
    bucket_lines: list[str] = []
    bucket_second: int | None = None
    bucket_has_zda = False
    bucket_datetime: datetime | None = None
    bucket_talker_id = DEFAULT_TALKER_ID
    last_known_date: date | None = None

    def flush_bucket() -> None:
        nonlocal bucket_lines, bucket_second, bucket_has_zda, bucket_datetime, bucket_talker_id
        if not bucket_lines:
            return

        output.extend(bucket_lines)
        if not bucket_has_zda and bucket_datetime is not None:
            output.append(
                build_zda_sentence(
                    now_utc=bucket_datetime,
                    talker_id=bucket_talker_id,
                    zone_hours=zone_hours,
                    zone_minutes=zone_minutes,
                )
            )

        bucket_lines = []
        bucket_second = None
        bucket_has_zda = False
        bucket_datetime = None
        bucket_talker_id = DEFAULT_TALKER_ID

    for sentence in sentences:
        time_seconds = extract_nmea_time_seconds(sentence)
        sentence_second = int(time_seconds) if time_seconds is not None else None
        sentence_type = extract_nmea_sentence_type(sentence)
        sentence_date = parse_nmea_date(sentence)
        sentence_talker_id = extract_nmea_talker_id(sentence)

        if sentence_second is not None:
            if bucket_second is None:
                bucket_second = sentence_second
            elif sentence_second != bucket_second:
                flush_bucket()
                bucket_second = sentence_second

        bucket_lines.append(sentence)

        if sentence_date is not None:
            last_known_date = sentence_date

        if sentence_type == "ZDA":
            bucket_has_zda = True

        if time_seconds is not None:
            if sentence_date is not None:
                bucket_datetime = combine_nmea_date_time(sentence_date, time_seconds)
                bucket_talker_id = sentence_talker_id
            elif bucket_datetime is None and last_known_date is not None:
                bucket_datetime = combine_nmea_date_time(last_known_date, time_seconds)
                bucket_talker_id = sentence_talker_id

    flush_bucket()
    return output


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Send NMEA time / GNSS-like sentences over the Jetson header UART.",
        epilog=(
            "Jetson AGX Orin dev kit header reference: pin 8 = UART1_TX, "
            "pin 10 = UART1_RX. Use 3.3V TTL serial. Ellipse box units need "
            "a TTL-to-RS-232/RS-422 level converter."
        ),
    )
    parser.add_argument(
        "--port",
        default=DEFAULT_PORT,
        help=f"serial device node for the UART header (default: {DEFAULT_PORT})",
    )
    parser.add_argument(
        "--input-file",
        default=None,
        help="replay NMEA sentences from a file instead of generating them",
    )
    parser.add_argument(
        "--baudrate",
        type=int,
        default=DEFAULT_BAUDRATE,
        help=f"serial baudrate (default: {DEFAULT_BAUDRATE})",
    )
    parser.add_argument(
        "--profile",
        choices=("sbg", "zda"),
        default="sbg",
        help=(
            "sentence profile to emit: 'sbg' sends RMC/GGA/GST and ZDA, "
            "plus HDT if --heading-deg is set; 'zda' preserves the original "
            "ZDA-only behavior (default: sbg)"
        ),
    )
    parser.add_argument(
        "--talker-id",
        default=DEFAULT_TALKER_ID,
        help=f"two-character NMEA talker ID (default: {DEFAULT_TALKER_ID})",
    )
    parser.add_argument(
        "--rate",
        type=float,
        default=None,
        help=(
            "send frequency in Hz; for --profile sbg this applies to "
            "RMC/GGA/GST/(HDT) with ZDA still sent at 1 Hz "
            f"(defaults: sbg={DEFAULT_SBG_RATE_HZ}, zda={DEFAULT_ZDA_RATE_HZ})"
        ),
    )
    parser.add_argument(
        "--count",
        type=int,
        default=0,
        help=(
            "number of output cycles to send; with --input-file this means "
            "file replay passes; 0 means run until Ctrl+C"
        ),
    )
    parser.add_argument(
        "--replay-speed",
        type=float,
        default=DEFAULT_FILE_REPLAY_SPEED,
        help=(
            "speed multiplier for --input-file timing; 1.0 preserves file timing, "
            "10.0 replays 10x faster"
        ),
    )
    parser.add_argument(
        "--no-replay-timing",
        action="store_true",
        help="with --input-file, send lines back-to-back without timestamp-based delays",
    )
    parser.add_argument(
        "--no-auto-zda",
        action="store_true",
        help="with --input-file, do not auto-insert missing ZDA sentences",
    )
    parser.add_argument(
        "--zone-hours",
        type=int,
        default=None,
        help="override local zone hours field in ZDA, for example 1 or -5",
    )
    parser.add_argument(
        "--zone-minutes",
        type=int,
        default=None,
        help="override local zone minutes field in ZDA, for example 0, 30, or 45",
    )
    parser.add_argument(
        "--latitude",
        type=float,
        default=None,
        help="latitude in decimal degrees for RMC/GGA (for example 52.5200)",
    )
    parser.add_argument(
        "--longitude",
        type=float,
        default=None,
        help="longitude in decimal degrees for RMC/GGA (for example 13.4050)",
    )
    parser.add_argument(
        "--no-simulated-fix",
        action="store_true",
        help=(
            "in --profile sbg, do not auto-fill a synthetic valid position when "
            "--latitude/--longitude are omitted"
        ),
    )
    parser.add_argument(
        "--altitude-m",
        type=float,
        default=None,
        help="altitude above mean sea level in meters for GGA",
    )
    parser.add_argument(
        "--geoid-separation-m",
        type=float,
        default=None,
        help="geoid separation in meters for GGA (default: 0.0 when fix is valid)",
    )
    parser.add_argument(
        "--speed-knots",
        type=float,
        default=None,
        help="ground speed in knots for RMC (default: 0.0)",
    )
    parser.add_argument(
        "--course-deg",
        type=float,
        default=None,
        help="course over ground in degrees for RMC (default: 0.0)",
    )
    parser.add_argument(
        "--fix-quality",
        type=int,
        default=None,
        help=(
            "GGA fix quality: 0=no fix, 1=GPS, 2=DGPS, 4=RTK fixed, 5=RTK float "
            "(default: 1 when lat/lon are provided, otherwise 0)"
        ),
    )
    parser.add_argument(
        "--num-satellites",
        type=int,
        default=None,
        help="satellites used in GGA (default: 12 with fix, otherwise 0)",
    )
    parser.add_argument(
        "--hdop",
        type=float,
        default=None,
        help="horizontal dilution of precision for GGA (default: 0.8 with fix, otherwise 99.9)",
    )
    parser.add_argument(
        "--heading-deg",
        type=float,
        default=None,
        help="true heading in degrees for optional HDT output",
    )
    parser.add_argument(
        "--gst-rms",
        type=float,
        default=None,
        help="GST RMS pseudorange error in meters (synthetic default: 1.0 with fix)",
    )
    parser.add_argument(
        "--gst-sigma-major",
        type=float,
        default=None,
        help="GST semi-major error in meters (synthetic default: 1.0 with fix)",
    )
    parser.add_argument(
        "--gst-sigma-minor",
        type=float,
        default=None,
        help="GST semi-minor error in meters (synthetic default: 1.0 with fix)",
    )
    parser.add_argument(
        "--gst-orientation-deg",
        type=float,
        default=None,
        help="GST error ellipse orientation in degrees (synthetic default: 0.0 with fix)",
    )
    parser.add_argument(
        "--gst-sigma-lat",
        type=float,
        default=None,
        help="GST latitude sigma in meters (synthetic default: 1.0 with fix)",
    )
    parser.add_argument(
        "--gst-sigma-lon",
        type=float,
        default=None,
        help="GST longitude sigma in meters (synthetic default: 1.0 with fix)",
    )
    parser.add_argument(
        "--gst-sigma-alt",
        type=float,
        default=None,
        help="GST altitude sigma in meters (synthetic default: 1.5 with fix)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print the NMEA sentences without opening the serial port",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="do not print each transmitted sentence",
    )
    parser.add_argument(
        "--align-second",
        action="store_true",
        help="wait until the next full UTC second before starting to send",
    )
    args = parser.parse_args()

    args.talker_id = args.talker_id.upper()
    if len(args.talker_id) != 2:
        parser.error("--talker-id must be exactly two characters")
    if args.rate is None:
        if args.profile == "sbg":
            args.rate = DEFAULT_SBG_RATE_HZ
        else:
            args.rate = DEFAULT_ZDA_RATE_HZ
    if args.rate <= 0:
        parser.error("--rate must be greater than 0")
    if args.count < 0:
        parser.error("--count must be >= 0")
    if args.replay_speed <= 0:
        parser.error("--replay-speed must be greater than 0")
    if (args.latitude is None) != (args.longitude is None):
        parser.error("--latitude and --longitude must be provided together")
    if args.latitude is not None and not -90.0 <= args.latitude <= 90.0:
        parser.error("--latitude must be between -90 and +90 degrees")
    if args.longitude is not None and not -180.0 <= args.longitude <= 180.0:
        parser.error("--longitude must be between -180 and +180 degrees")
    if args.fix_quality is not None and not 0 <= args.fix_quality <= 8:
        parser.error("--fix-quality must be between 0 and 8")
    if args.num_satellites is not None and not 0 <= args.num_satellites <= 99:
        parser.error("--num-satellites must be between 0 and 99")
    if args.heading_deg is not None and not 0.0 <= args.heading_deg < 360.0:
        parser.error("--heading-deg must be between 0.0 and <360.0")

    return args


def maybe_align_to_next_second() -> None:
    now = datetime.now(timezone.utc)
    next_second = (now + timedelta(seconds=1)).replace(microsecond=0)
    sleep_seconds = (next_second - now).total_seconds()
    if sleep_seconds > 0:
        time.sleep(sleep_seconds)


def resolve_sbg_profile(args: argparse.Namespace) -> dict[str, float | int | bool | None]:
    latitude = args.latitude
    longitude = args.longitude
    altitude_m = args.altitude_m
    using_simulated_fix = False
    position_available = latitude is not None and longitude is not None

    if args.profile == "sbg" and not position_available and not args.no_simulated_fix:
        latitude = DEFAULT_SIMULATED_LATITUDE
        longitude = DEFAULT_SIMULATED_LONGITUDE
        if altitude_m is None:
            altitude_m = DEFAULT_SIMULATED_ALTITUDE_M
        position_available = True
        using_simulated_fix = True

    fix_quality = args.fix_quality
    if fix_quality is None:
        fix_quality = 1 if position_available else 0

    valid_fix = position_available and fix_quality > 0
    num_satellites = (
        args.num_satellites if args.num_satellites is not None else (12 if valid_fix else 0)
    )
    hdop = args.hdop if args.hdop is not None else (0.8 if valid_fix else 99.9)
    altitude_m = altitude_m if valid_fix else None
    geoid_separation_m = (
        args.geoid_separation_m
        if args.geoid_separation_m is not None
        else (0.0 if valid_fix else None)
    )
    speed_knots = args.speed_knots if args.speed_knots is not None else 0.0
    course_deg = args.course_deg if args.course_deg is not None else 0.0

    if valid_fix:
        gst_rms = args.gst_rms if args.gst_rms is not None else 1.0
        gst_sigma_major = (
            args.gst_sigma_major if args.gst_sigma_major is not None else 1.0
        )
        gst_sigma_minor = (
            args.gst_sigma_minor if args.gst_sigma_minor is not None else 1.0
        )
        gst_orientation_deg = (
            args.gst_orientation_deg if args.gst_orientation_deg is not None else 0.0
        )
        gst_sigma_lat = args.gst_sigma_lat if args.gst_sigma_lat is not None else 1.0
        gst_sigma_lon = args.gst_sigma_lon if args.gst_sigma_lon is not None else 1.0
        gst_sigma_alt = args.gst_sigma_alt if args.gst_sigma_alt is not None else 1.5
    else:
        gst_rms = args.gst_rms
        gst_sigma_major = args.gst_sigma_major
        gst_sigma_minor = args.gst_sigma_minor
        gst_orientation_deg = args.gst_orientation_deg
        gst_sigma_lat = args.gst_sigma_lat
        gst_sigma_lon = args.gst_sigma_lon
        gst_sigma_alt = args.gst_sigma_alt

    return {
        "using_simulated_fix": using_simulated_fix,
        "valid_fix": valid_fix,
        "latitude": latitude,
        "longitude": longitude,
        "fix_quality": fix_quality,
        "num_satellites": num_satellites,
        "hdop": hdop,
        "altitude_m": altitude_m,
        "geoid_separation_m": geoid_separation_m,
        "speed_knots": speed_knots,
        "course_deg": course_deg,
        "heading_deg": args.heading_deg,
        "gst_rms": gst_rms,
        "gst_sigma_major": gst_sigma_major,
        "gst_sigma_minor": gst_sigma_minor,
        "gst_orientation_deg": gst_orientation_deg,
        "gst_sigma_lat": gst_sigma_lat,
        "gst_sigma_lon": gst_sigma_lon,
        "gst_sigma_alt": gst_sigma_alt,
    }


def build_sentence_batch(
    now_utc: datetime,
    args: argparse.Namespace,
    profile: dict[str, float | int | bool | None],
    zone_hours: int,
    zone_minutes: int,
    last_zda_second: datetime | None,
) -> tuple[list[str], datetime | None]:
    if args.profile == "zda":
        return [
            build_zda_sentence(
                now_utc=now_utc,
                talker_id=args.talker_id,
                zone_hours=zone_hours,
                zone_minutes=zone_minutes,
            )
        ], last_zda_second

    sentences = [
        build_rmc_sentence(
            now_utc=now_utc,
            talker_id=args.talker_id,
            latitude=profile["latitude"],
            longitude=profile["longitude"],
            speed_knots=float(profile["speed_knots"]),
            course_deg=float(profile["course_deg"]),
            valid_fix=bool(profile["valid_fix"]),
        ),
        build_gga_sentence(
            now_utc=now_utc,
            talker_id=args.talker_id,
            latitude=profile["latitude"],
            longitude=profile["longitude"],
            altitude_m=profile["altitude_m"],
            geoid_separation_m=profile["geoid_separation_m"],
            fix_quality=int(profile["fix_quality"]),
            num_satellites=int(profile["num_satellites"]),
            hdop=float(profile["hdop"]),
        ),
        build_gst_sentence(
            now_utc=now_utc,
            talker_id=args.talker_id,
            gst_rms=profile["gst_rms"],
            gst_sigma_major=profile["gst_sigma_major"],
            gst_sigma_minor=profile["gst_sigma_minor"],
            gst_orientation_deg=profile["gst_orientation_deg"],
            gst_sigma_lat=profile["gst_sigma_lat"],
            gst_sigma_lon=profile["gst_sigma_lon"],
            gst_sigma_alt=profile["gst_sigma_alt"],
        ),
    ]

    if profile["heading_deg"] is not None:
        sentences.append(
            build_hdt_sentence(
                talker_id=args.talker_id,
                heading_deg=float(profile["heading_deg"]),
            )
        )

    this_second = now_utc.replace(microsecond=0)
    if last_zda_second != this_second:
        sentences.append(
            build_zda_sentence(
                now_utc=now_utc,
                talker_id=args.talker_id,
                zone_hours=zone_hours,
                zone_minutes=zone_minutes,
            )
        )
        last_zda_second = this_second

    return sentences, last_zda_second


def replay_nmea_file(
    args: argparse.Namespace,
    stream,
    zone_hours: int,
    zone_minutes: int,
) -> int:
    sentences = load_nmea_file(args.input_file)
    if not args.no_auto_zda:
        sentences = inject_missing_zda_sentences(
            sentences=sentences,
            zone_hours=zone_hours,
            zone_minutes=zone_minutes,
        )
    pass_count = 0

    while _RUNNING and (args.count == 0 or pass_count < args.count):
        last_time_seconds = None
        for sentence in sentences:
            if not _RUNNING:
                break

            if not args.no_replay_timing:
                current_time_seconds = extract_nmea_time_seconds(sentence)
                if current_time_seconds is not None and last_time_seconds is not None:
                    delta = current_time_seconds - last_time_seconds
                    # Auto-generated ZDA sentences use hundredths precision while
                    # many GNSS logs use milliseconds, so allow tiny backward
                    # steps without treating them as a day rollover.
                    if delta < 0 and abs(delta) < 1.0:
                        delta = 0.0
                    elif delta < 0:
                        delta += 24 * 3600
                    sleep_seconds = delta / args.replay_speed
                    if sleep_seconds > 0:
                        time.sleep(sleep_seconds)
                if current_time_seconds is not None:
                    last_time_seconds = current_time_seconds

            if stream is not None:
                stream.write(sentence.encode("ascii"))
                stream.flush()

            if not args.quiet:
                stamp = datetime.now(timezone.utc).strftime("%H:%M:%S.%f")[:-3]
                mode = "DRY-RUN" if args.dry_run else "TX"
                print(f"[{stamp} UTC] {mode}: {sentence.strip()}")

        pass_count += 1

    return 0


def send_loop(args: argparse.Namespace) -> int:
    zone_hours, zone_minutes = normalize_zone_offset(
        args.zone_hours, args.zone_minutes
    )
    stream = None
    if not args.dry_run:
        stream = serial.Serial(
            port=args.port,
            baudrate=args.baudrate,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=1,
            write_timeout=1,
        )
        stream.reset_input_buffer()
        stream.reset_output_buffer()

    try:
        if args.input_file:
            if not args.quiet:
                replay_mode = "timed" if not args.no_replay_timing else "burst"
                print(
                    f"replaying NMEA file {args.input_file} to {args.port} "
                    f"at {args.baudrate} baud ({replay_mode}, speed x{args.replay_speed:g})",
                    file=sys.stderr,
                )
                if not args.no_auto_zda:
                    print(
                        "note: auto-inserting ZDA once per second when the replay "
                        "file doesn't already provide it.",
                        file=sys.stderr,
                    )
            return replay_nmea_file(
                args=args,
                stream=stream,
                zone_hours=zone_hours,
                zone_minutes=zone_minutes,
            )

        profile = resolve_sbg_profile(args)

        if args.align_second:
            maybe_align_to_next_second()

        if args.profile == "sbg" and not args.quiet:
            print(
                "note: SBG external NMEA aiding normally also expects a 1 Hz PPS "
                "signal on a Sync input; this script only emits serial NMEA.",
                file=sys.stderr,
            )
            if profile["using_simulated_fix"]:
                print(
                    "note: no latitude/longitude supplied; using a synthetic fixed "
                    f"position ({profile['latitude']:.4f}, {profile['longitude']:.4f}) "
                    "to emulate a valid GNSS receiver.",
                    file=sys.stderr,
                )
            elif not profile["valid_fix"]:
                print(
                    "note: no latitude/longitude fix configured; RMC/GGA/GST will "
                    "be emitted as no-fix placeholders plus ZDA.",
                    file=sys.stderr,
                )

        interval = 1.0 / args.rate
        next_deadline = time.monotonic()
        cycle_count = 0
        last_zda_second = None

        while _RUNNING and (args.count == 0 or cycle_count < args.count):
            now_utc = datetime.now(timezone.utc)
            sentences, last_zda_second = build_sentence_batch(
                now_utc=now_utc,
                args=args,
                profile=profile,
                zone_hours=zone_hours,
                zone_minutes=zone_minutes,
                last_zda_second=last_zda_second,
            )

            if stream is not None:
                stream.write("".join(sentences).encode("ascii"))
                stream.flush()

            if not args.quiet:
                stamp = now_utc.strftime("%H:%M:%S.%f")[:-3]
                mode = "DRY-RUN" if args.dry_run else "TX"
                for sentence in sentences:
                    print(f"[{stamp} UTC] {mode}: {sentence.strip()}")

            cycle_count += 1
            next_deadline += interval
            sleep_seconds = next_deadline - time.monotonic()
            if sleep_seconds > 0:
                time.sleep(sleep_seconds)
            else:
                next_deadline = time.monotonic()

        return 0
    finally:
        if stream is not None and stream.is_open:
            stream.close()


def main() -> int:
    serial_module, serial_error = resolve_pyserial()
    if serial_error is not None:
        print(serial_error, file=sys.stderr)
        return 3

    args = parse_args()
    signal.signal(signal.SIGINT, _handle_stop)
    signal.signal(signal.SIGTERM, _handle_stop)

    try:
        globals()["serial"] = serial_module
        return send_loop(args)
    except ValueError as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return 2
    except serial_module.SerialException as exc:
        print(f"serial error: {exc}", file=sys.stderr)
        print(
            f"check the UART device node and permissions for {args.port}",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
