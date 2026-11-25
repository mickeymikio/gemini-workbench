"""Route definitions, carrier classifications, and runtime thresholds."""

from __future__ import annotations

from dataclasses import dataclass

MIN_DAYS_AHEAD: int = 7
MAX_DAYS_AHEAD: int = 180
DEAL_DISCOUNT_THRESHOLD_PCT: float = 40.0
CIRCUIT_BREAKER_CONSECUTIVE_BLOCKS: int = 2


@dataclass(frozen=True)
class RouteSpec:
    origin: str
    dest: str
    city_ja: str
    stay_nights: tuple[int, ...]
    is_long_haul: bool = False

    @property
    def code(self) -> str:
        return f"{self.origin}-{self.dest}"

    @property
    def label_ja(self) -> str:
        return f"{self.origin}→{self.dest}（{self.city_ja}）"


ROUTES_15: tuple[RouteSpec, ...] = (
    RouteSpec("NRT", "ICN", "ソウル仁川", (3, 4, 5)),
    RouteSpec("HND", "GMP", "ソウル金浦", (3, 4, 5)),
    RouteSpec("NRT", "TPE", "台北桃園", (3, 4, 5)),
    RouteSpec("HND", "TSA", "台北松山", (3, 4, 5)),
    RouteSpec("NRT", "HKG", "香港", (3, 4, 5)),
    RouteSpec("NRT", "BKK", "バンコク", (3, 4, 5)),
    RouteSpec("HND", "SIN", "シンガポール", (3, 4, 5)),
    RouteSpec("NRT", "HNL", "ホノルル", (5, 6, 7), is_long_haul=True),
    RouteSpec("HND", "LAX", "ロサンゼルス", (5, 6, 7), is_long_haul=True),
    RouteSpec("NRT", "SGN", "ホーチミン", (3, 4, 5)),
    RouteSpec("NRT", "SYD", "シドニー", (5, 6, 7), is_long_haul=True),
    RouteSpec("NRT", "HAN", "ハノイ", (3, 4, 5)),
    RouteSpec("NRT", "MNL", "マニラ", (3, 4, 5)),
    RouteSpec("NRT", "SAI", "シェムリアップ", (3, 4, 5)),
    RouteSpec("NRT", "DAD", "ダナン", (3, 4, 5)),
)

ROUTE_BY_CODE: dict[str, RouteSpec] = {r.code: r for r in ROUTES_15}

TARGET_SITES: tuple[str, ...] = (
    "Google Flights",
    "KAYAK",
    "Cheapflights",
    "momondo",
    "Priceline",
    "catchfrog.ai",
    "Skyscanner",
)

LCC_KEYWORDS: tuple[str, ...] = (
    "zipair",
    "ジップエア",
    "vietjet",
    "ベトジェット",
    "scoot",
    "スクート",
    "peach",
    "ピーチ",
    "jetstar",
    "ジェットスター",
    "jeju air",
    "jeju",
    "チェジュ",
    "済州",
    "t'way",
    "tway",
    "ティーウェイ",
    "jin air",
    "ジンエアー",
    "air busan",
    "エアプサン",
    "air seoul",
    "エアソウル",
    "eastar",
    "イースター",
    "aero k",
    "エアロk",
    "air premia",
    "エアプレミア",
    "tigerair",
    "タイガーエア",
    "hk express",
    "香港エクスプレス",
    "greater bay",
    "グレーターベイ",
    "airasia",
    "エアアジア",
    "cebu pacific",
    "セブパシフィック",
    "spring",
    "スプリング",
    "春秋",
    "thai lion",
    "ライオン・エア",
    "ライオンエア",
    "batik",
    "バティック",
    "vietravel",
)


def is_lcc_airline(airline_text: str) -> bool:
    """Return True if any operating/marketing carrier in `airline_text` matches known LCCs."""
    lowered = airline_text.lower()
    return any(kw in lowered for kw in LCC_KEYWORDS)
