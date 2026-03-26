"""
Parser for Makerfabs ESP32 UWB Pro serial output.

Handles the default firmware output format including:
- Main measurement lines: from: <HEX> Range: <FLOAT> m  RX power: <FLOAT> dBm
- Device-added lines: ranging init; N device added ! -> short:<HEX>
- Device-inactive lines: delete inactive device: <HEX>
- Known debug/noise lines
- Unknown lines (stored for debugging, never crash)
"""

import re
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ParseResult:
    """Result of parsing a single serial line."""
    line_type: str  # 'measurement', 'device_added', 'device_inactive', 'debug_noise', 'blank', 'unknown'
    short_addr_hex: Optional[str] = None
    short_addr_int: Optional[int] = None
    range_m: Optional[float] = None
    rx_power_dbm: Optional[float] = None
    event_type: Optional[str] = None
    event_text: Optional[str] = None
    raw_text: str = ''


# --- Compiled regex patterns ---

# Main measurement line:
#   from: 1786	Range: 2.43 m	RX power: -75.31 dBm
# Accept tabs or multiple spaces as separators.
MEASUREMENT_RE = re.compile(
    r'from:\s*([0-9A-Fa-f]+)\s+Range:\s*([-]?\d+(?:\.\d+)?)\s*m\s+RX\s*power:\s*([-]?\d+(?:\.\d+)?)\s*dBm',
    re.IGNORECASE
)

# Device added via ranging init or blink:
#   ranging init; 1 device added ! ->  short:1786
#   blink; 1 device added ! ->  short:1786
DEVICE_ADDED_RE = re.compile(
    r'(?:ranging init|blink);\s*\d+\s+device\s+added\s*!\s*->\s*short:([0-9A-Fa-f]+)',
    re.IGNORECASE
)

# Device inactive:
#   delete inactive device: 1786
DEVICE_INACTIVE_RE = re.compile(
    r'delete\s+inactive\s+device:\s*([0-9A-Fa-f]+)',
    re.IGNORECASE
)

# Known debug/noise patterns that should be silently categorized
NOISE_PATTERNS = [
    re.compile(r'^add_link:', re.IGNORECASE),
    re.compile(r'^find_link:', re.IGNORECASE),
    re.compile(r'^fresh_link:', re.IGNORECASE),
]

# Bare hex address (2-8 hex chars, whole line)
BARE_HEX_RE = re.compile(r'^[0-9A-Fa-f]{2,8}$')

# Bare float (whole line)
BARE_FLOAT_RE = re.compile(r'^[-]?\d+\.\d+$')


def normalize_short_addr(addr: str) -> str:
    """Normalize a short address to uppercase hex without 0x prefix."""
    return addr.strip().upper()


def parse_short_addr_int(hex_str: str) -> Optional[int]:
    """Convert hex address string to int, or None on failure."""
    try:
        return int(hex_str, 16)
    except (ValueError, TypeError):
        return None


def parse_line(line: str) -> ParseResult:
    """
    Parse a single serial line from the Makerfabs UWB firmware.

    Returns a ParseResult with the identified line type and extracted fields.
    Never raises exceptions on malformed input.
    """
    raw = line
    line = line.strip('\r\n').strip()

    # Blank lines
    if not line:
        return ParseResult(line_type='blank', raw_text=raw)

    # Main measurement pattern
    m = MEASUREMENT_RE.search(line)
    if m:
        addr = normalize_short_addr(m.group(1))
        try:
            range_m = float(m.group(2))
            rx_power = float(m.group(3))
        except ValueError:
            return ParseResult(line_type='unknown', raw_text=raw, event_text=line)
        return ParseResult(
            line_type='measurement',
            short_addr_hex=addr,
            short_addr_int=parse_short_addr_int(addr),
            range_m=range_m,
            rx_power_dbm=rx_power,
            raw_text=raw,
        )

    # Device added
    m = DEVICE_ADDED_RE.search(line)
    if m:
        addr = normalize_short_addr(m.group(1))
        return ParseResult(
            line_type='device_added',
            short_addr_hex=addr,
            short_addr_int=parse_short_addr_int(addr),
            event_type='device_added',
            event_text=line,
            raw_text=raw,
        )

    # Device inactive
    m = DEVICE_INACTIVE_RE.search(line)
    if m:
        addr = normalize_short_addr(m.group(1))
        return ParseResult(
            line_type='device_inactive',
            short_addr_hex=addr,
            short_addr_int=parse_short_addr_int(addr),
            event_type='device_inactive',
            event_text=line,
            raw_text=raw,
        )

    # Known debug/noise patterns
    for pattern in NOISE_PATTERNS:
        if pattern.search(line):
            return ParseResult(line_type='debug_noise', event_text=line, raw_text=raw)

    # Bare hex address (display refresh artifact)
    if BARE_HEX_RE.match(line):
        return ParseResult(line_type='debug_noise', event_text=line, raw_text=raw)

    # Bare float (display refresh artifact)
    if BARE_FLOAT_RE.match(line):
        return ParseResult(line_type='debug_noise', event_text=line, raw_text=raw)

    # Unknown line — store but don't crash
    return ParseResult(line_type='unknown', event_text=line, raw_text=raw)
