"""Pure-Python Google Flights `tfs` Protobuf wire-format URL encoder.

Zero external scraper dependencies; natively supports all 3-letter IATA airport codes
including newly opened airports such as `SAI` (Siem Reap Angkor International).
"""

from __future__ import annotations

import base64
from datetime import date


def _encode_varint(value: int) -> bytes:
    if value < 0:
        raise ValueError(f"Varint must be non-negative, got {value}")
    out = bytearray()
    while value > 0x7F:
        out.append((value & 0x7F) | 0x80)
        value >>= 7
    out.append(value)
    return bytes(out)


def _field_varint(field_number: int, value: int) -> bytes:
    return _encode_varint((field_number << 3) | 0) + _encode_varint(value)


def _field_bytes(field_number: int, payload: bytes | str) -> bytes:
    raw = payload.encode("utf-8") if isinstance(payload, str) else payload
    return _encode_varint((field_number << 3) | 2) + _encode_varint(len(raw)) + raw


def encode_roundtrip_tfs(
    origin: str,
    dest: str,
    dep_date: str,
    ret_date: str,
    adults: int = 1,
    seat_class: int = 1,
) -> str:
    """Encode a round-trip economy query pinned to exact 3-letter IATA airport codes.

    `seat_class`: 1=Economy, 2=Premium Economy, 3=Business, 4=First.
    """
    orig_code = origin.strip().upper()
    dest_code = dest.strip().upper()
    if len(orig_code) != 3 or not orig_code.isalpha():
        raise ValueError(f"Origin must be a 3-letter IATA airport code, got {origin!r}")
    if len(dest_code) != 3 or not dest_code.isalpha():
        raise ValueError(f"Destination must be a 3-letter IATA airport code, got {dest!r}")

    d1 = date.fromisoformat(dep_date)
    d2 = date.fromisoformat(ret_date)
    if d2 <= d1:
        raise ValueError(f"ret_date ({ret_date}) must be after dep_date ({dep_date})")

    # Location message: field 1 = 1 (IATA airport type, NOT city), field 2 = 3-letter IATA code
    orig_loc = _field_varint(1, 1) + _field_bytes(2, orig_code)
    dest_loc = _field_varint(1, 1) + _field_bytes(2, dest_code)

    leg_out = _field_bytes(2, dep_date) + _field_bytes(13, orig_loc) + _field_bytes(14, dest_loc)
    leg_ret = _field_bytes(2, ret_date) + _field_bytes(13, dest_loc) + _field_bytes(14, orig_loc)

    # Root FlightSearch message:
    # field 1 = 28 (schema version), field 2 = 2 (round-trip),
    # repeated field 3 = legs, field 8 = adult passenger count,
    # field 9 = cabin class, field 19 = 1 (round-trip pricing mode)
    msg = (
        _field_varint(1, 28)
        + _field_varint(2, 2)
        + _field_bytes(3, leg_out)
        + _field_bytes(3, leg_ret)
        + _field_varint(8, adults)
        + _field_varint(9, seat_class)
        + _field_varint(19, 1)
    )
    return base64.urlsafe_b64encode(msg).decode("ascii").rstrip("=")


def build_google_flights_url(
    origin: str,
    dest: str,
    dep_date: str,
    ret_date: str,
    hl: str = "ja",
    gl: str = "JP",
    curr: str = "JPY",
) -> str:
    """Build a direct, reproducible date-embedded Google Flights search URL."""
    tfs = encode_roundtrip_tfs(origin, dest, dep_date, ret_date)
    return f"https://www.google.com/travel/flights/search?tfs={tfs}&hl={hl}&gl={gl}&curr={curr}"
