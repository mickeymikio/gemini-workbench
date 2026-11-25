"""Strict Pydantic data models enforcing same-site comparison and airport code accuracy."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field, model_validator

JST = ZoneInfo("Asia/Tokyo")
WEEKDAYS_JA: tuple[str, ...] = ("月", "火", "水", "木", "金", "土", "日")


def format_date_ja(iso_date: str) -> str:
    """Convert YYYY-MM-DD into 'YYYY年MM月DD日（曜）'."""
    d = date.fromisoformat(iso_date)
    wd = WEEKDAYS_JA[d.weekday()]
    return f"{d.year}年{d.month:02d}月{d.day:02d}日（{wd}）"


def format_money(amount: float, currency: str) -> str:
    cur = currency.upper()
    if cur == "JPY":
        return f"¥{int(round(amount)):,}（JPY）"
    if cur == "KRW":
        return f"₩{int(round(amount)):,}（KRW）"
    if cur == "USD":
        if abs(amount - round(amount)) < 0.005:
            return f"${int(round(amount)):,}（USD）"
        return f"${amount:,.2f}（USD）"
    return f"{amount:,.2f} {cur}"


class FlightObservation(BaseModel):
    route_code: str
    origin: str
    dest: str
    city_ja: str
    verified_origin: str
    verified_dest: str
    verified_return_origin: str | None = None
    verified_return_dest: str | None = None
    dep_date: str
    ret_date: str
    airline: str
    lowest_price: float = Field(gt=0)
    currency: str
    tax_status: Literal["税込", "税別", "税込表記確認不可"] = "税込"
    typical_price: float | None = Field(default=None, gt=0)
    typical_low: float | None = Field(default=None, gt=0)
    typical_high: float | None = Field(default=None, gt=0)
    typical_currency: str | None = None
    typical_source_site: str | None = None
    source_site: str
    search_url: str
    stops_text: str
    is_lcc: bool = False
    checked_baggage: str | None = None
    seats_remaining: str | None = None
    extra_note: str | None = None
    observed_at_jst: str = Field(
        default_factory=lambda: datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S JST")
    )

    @model_validator(mode="after")
    def _validate_integrity(self) -> "FlightObservation":
        # 1. Date sanity
        d_dep = date.fromisoformat(self.dep_date)
        d_ret = date.fromisoformat(self.ret_date)
        if d_ret <= d_dep:
            raise ValueError(f"ret_date ({self.ret_date}) must be after dep_date ({self.dep_date})")

        # 2. Exact IATA co-terminal enforcement (prevent NRT/HND, ICN/GMP, TPE/TSA, BKK/DMK mix-ups)
        if self.verified_origin.upper() != self.origin.upper():
            raise ValueError(
                f"Origin airport mismatch on {self.route_code}: expected {self.origin}, got {self.verified_origin}"
            )
        if self.verified_dest.upper() != self.dest.upper():
            raise ValueError(
                f"Destination airport mismatch on {self.route_code}: expected {self.dest}, got {self.verified_dest}"
            )
        if self.verified_return_origin and self.verified_return_origin.upper() != self.dest.upper():
            raise ValueError(
                f"Return origin airport mismatch on {self.route_code}: expected {self.dest}, got {self.verified_return_origin}"
            )
        if self.verified_return_dest and self.verified_return_dest.upper() != self.origin.upper():
            raise ValueError(
                f"Return destination airport mismatch on {self.route_code}: expected {self.origin}, got {self.verified_return_dest}"
            )

        # 3. URL must be a real HTTPS search URL
        if not self.search_url.startswith("https://"):
            raise ValueError(f"search_url must start with https://, got {self.search_url!r}")

        # 4. Derive midpoint typical_price if typical_low & typical_high are set
        if self.typical_low is not None and self.typical_high is not None:
            if self.typical_high < self.typical_low:
                raise ValueError(
                    f"typical_high ({self.typical_high}) < typical_low ({self.typical_low})"
                )
            midpoint = (self.typical_low + self.typical_high) / 2.0
            if self.typical_price is None:
                self.typical_price = midpoint

        # 5. Strictly forbid cross-site or cross-currency typical price pairing
        if self.typical_price is not None:
            if not self.typical_source_site:
                raise ValueError("typical_source_site is required whenever typical_price is set")
            if self.typical_source_site != self.source_site:
                raise ValueError(
                    f"Cross-site typical price comparison is forbidden: "
                    f"lowest={self.source_site!r} vs typical={self.typical_source_site!r}"
                )
            if not self.typical_currency:
                raise ValueError("typical_currency is required whenever typical_price is set")
            if self.typical_currency.upper() != self.currency.upper():
                raise ValueError(
                    f"Cross-currency discount calculation is forbidden: "
                    f"lowest={self.currency!r} vs typical={self.typical_currency!r}"
                )

        return self

    @property
    def discount_pct(self) -> float | None:
        if self.typical_price is None or self.typical_price <= 0:
            return None
        raw = ((self.typical_price - self.lowest_price) / self.typical_price) * 100.0
        return round(raw, 1)

    @property
    def is_deal_40_off(self) -> bool:
        disc = self.discount_pct
        if disc is None:
            return False
        # Use unrounded exact ratio >= 40.0% check as well as rounded display consistency
        exact = ((self.typical_price - self.lowest_price) / self.typical_price) * 100.0  # type: ignore[operator]
        return exact >= 40.0


FailureCategory = Literal[
    "bot_block",
    "http_error",
    "login_required",
    "unsupported_route",
    "timeout",
    "no_results",
    "airport_mismatch",
    "circuit_breaker_skipped",
    "parse_error",
]


class FetchFailure(BaseModel):
    source_site: str
    route_code: str
    category: FailureCategory
    reason_ja: str
    attempted_url: str | None = None
    observed_at_jst: str = Field(
        default_factory=lambda: datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S JST")
    )
