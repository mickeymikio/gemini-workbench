"""Adapters for KAYAK, Cheapflights, momondo, Priceline, catchfrog.ai, and Skyscanner.

Strict compliance:
- Never solves or bypasses CAPTCHAs / anti-bot gates.
- Never borrows typical_price from another site (cross-site pairing is strictly forbidden).
- Never reports cached teaser/list prices (such as catchfrog.ai's OTA feed) as verified search prices.
"""

from __future__ import annotations

import re
from typing import TypedDict

from ..config import RouteSpec, is_lcc_airline
from ..models import FetchFailure, FlightObservation
from .base import detect_access_barrier

_YEN_PRICE_RE = re.compile(r"[¥￥]\s*([\d,]{4,9})")
_USD_PRICE_RE = re.compile(r"\$\s*([\d,]{2,7})")
_KAYAK_TYPICAL_JA_RE = re.compile(
    r"(?:通常の料金|一般的な料金|平均料金)[^\d¥￥]{0,15}[¥￥]\s*([\d,]+)(?:\s*[～〜~\-－]\s*[¥￥]?\s*([\d,]+))?"
)
_KAYAK_TYPICAL_EN_RE = re.compile(
    r"(?:typical price|usually costs?|good deal[^$\d]{0,20}usually)\s*\$\s*([\d,]+)(?:\s*[–\-—to]+\s*\$?\s*([\d,]+))?",
    re.IGNORECASE,
)

# Co-terminal rival airport codes that must NOT substitute for the requested airport
_COTERMINAL_RIVALS: dict[str, tuple[str, ...]] = {
    "NRT": ("HND",),
    "HND": ("NRT",),
    "ICN": ("GMP",),
    "GMP": ("ICN",),
    "TPE": ("TSA",),
    "TSA": ("TPE",),
    "BKK": ("DMK",),
}

_NOISE_AIRLINE_PREFIXES: tuple[str, ...] = (
    "検索結果が完全に読み込まれたら",
    "compare",
    "go to next",
    "次の結果",
    "sponsored",
    "スポンサー",
    "エコノミー",
    "economy",
    "select",
    "選択",
    "deal",
    "最安",
    "おすすめ",
    "best",
    "cheapest",
    "quickest",
)


class KayakCardDict(TypedDict):
    price_text: str
    carrier_text: str
    raw_text: str


def build_secondary_search_url(
    site_name: str, origin: str, dest: str, dep_date: str, ret_date: str
) -> str:
    o = origin.upper()
    d = dest.upper()
    if site_name == "KAYAK":
        return f"https://www.kayak.co.jp/flights/{o}-{d}/{dep_date}/{ret_date}?sort=price_a"
    if site_name == "Cheapflights":
        return f"https://www.cheapflights.com/flight-search/{o}-{d}/{dep_date}/{ret_date}?sort=price_a"
    if site_name == "momondo":
        return f"https://www.momondo.jp/flight-search/{o}-{d}/{dep_date}/{ret_date}?sort=price_a"
    if site_name == "Priceline":
        d1 = dep_date.replace("-", "")
        d2 = ret_date.replace("-", "")
        return f"https://www.priceline.com/m/fly/search/{o}-{d}-{d1}/{d}-{o}-{d2}/?cabin-class=ECO&num-adults=1"
    if site_name == "Skyscanner":
        s1 = dep_date[2:].replace("-", "")
        s2 = ret_date[2:].replace("-", "")
        return f"https://www.skyscanner.jp/transport/flights/{o.lower()}/{d.lower()}/{s1}/{s2}/"
    if site_name == "catchfrog.ai":
        return "https://catchfrog.ai/jp"
    raise ValueError(f"Unknown site: {site_name}")


def _extract_airline_from_nrc6(card: KayakCardDict, origin: str, dest: str) -> str:
    carriers = [
        c.strip()
        for c in card["carrier_text"].split("/")
        if c.strip() and not any(c.strip().lower().startswith(p) for p in _NOISE_AIRLINE_PREFIXES)
    ]
    if carriers:
        deduped: list[str] = []
        for c in carriers:
            if c not in deduped:
                deduped.append(c)
        return " ／ ".join(deduped[:2])

    lines = [ln.strip() for ln in card["raw_text"].splitlines() if ln.strip()]
    found_carriers: list[str] = []
    for ln in lines:
        low = ln.lower()
        if len(ln) < 2 or len(ln) > 55:
            continue
        if any(low.startswith(p) for p in _NOISE_AIRLINE_PREFIXES):
            continue
        if re.search(r"[¥￥$]|\d{1,2}:\d{2}|\d+\s*h\s*\d*|\d+\s*時間|\d+\s*分", ln):
            continue
        if ln.upper() in {origin.upper(), dest.upper(), "-", "–", "直行便", "NONSTOP", "DIRECT"}:
            continue
        if ln.upper().startswith(origin.upper()) or ln.upper().startswith(dest.upper()):
            continue
        if any(w in low for w in ("stop", "乗継", "経由", "手荷物", "bag", "carry-on", "+1", "+2")):
            continue
        if ln not in found_carriers:
            found_carriers.append(ln)
        if len(found_carriers) >= 2:
            break

    return " ／ ".join(found_carriers) if found_carriers else "航空会社名（画面カード参照）"


def _parse_kayak_family_screen(
    site_name: str,
    route: RouteSpec,
    dep_date: str,
    ret_date: str,
    search_url: str,
    cards: list[KayakCardDict],
    full_body_text: str,
) -> FlightObservation | FetchFailure:
    """Parse `.nrc6` result cards on KAYAK / Cheapflights / momondo."""
    expect_jpy = site_name in ("KAYAK", "momondo")
    currency = "JPY" if expect_jpy else "USD"
    price_re = _YEN_PRICE_RE if expect_jpy else _USD_PRICE_RE

    # Extract same-site typical price ONLY if explicitly displayed on this site's screen
    typ_low: float | None = None
    typ_high: float | None = None
    typ_pat = _KAYAK_TYPICAL_JA_RE if expect_jpy else _KAYAK_TYPICAL_EN_RE
    m_typ = typ_pat.search(full_body_text)
    if m_typ:
        v1 = float(m_typ.group(1).replace(",", ""))
        v2 = float(m_typ.group(2).replace(",", "")) if m_typ.group(2) else v1
        if 0 < v1 <= v2:
            typ_low, typ_high = v1, v2

    tax_status = "税込"
    if "税別" in full_body_text or "excludes taxes" in full_body_text.lower():
        tax_status = "税別"
    elif (
        "税込" not in full_body_text
        and "税金" not in full_body_text
        and "taxes and fees" not in full_body_text.lower()
        and expect_jpy is False
    ):
        tax_status = "税込表記確認不可"

    rivals = set(_COTERMINAL_RIVALS.get(route.origin.upper(), ())) | set(
        _COTERMINAL_RIVALS.get(route.dest.upper(), ())
    )

    best_obs: FlightObservation | None = None

    for card in cards:
        raw = card["raw_text"]
        # Must include both requested IATA codes (KAYAK renders e.g. 'NRT成田国際空港' or 'HND')
        if not re.search(rf"\b{re.escape(route.origin.upper())}", raw):
            continue
        if not re.search(rf"\b{re.escape(route.dest.upper())}", raw):
            continue
        # Reject co-terminal substitutions (e.g. NRT leg inside an HND search or DMK inside BKK)
        if any(re.search(rf"\b{re.escape(rv)}", raw) for rv in rivals):
            continue

        # Parse dedicated `.f8F1-price-text` / `[class*="price-text"]` first to avoid upsell/baggage badges!
        m_main_price = price_re.search(card["price_text"])
        if not m_main_price:
            continue
        card_price = float(m_main_price.group(1).replace(",", ""))
        min_reasonable = 8000.0 if currency == "JPY" else 80.0
        if card_price < min_reasonable:
            continue

        lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
        stops_text = "経由あり"
        nonstop_hits = sum(
            1 for ln in lines if ("直行" in ln or "nonstop" in ln.lower() or "direct" in ln.lower())
        )
        if nonstop_hits >= 1 and not any(
            ("乗継" in ln or "経由" in ln or re.search(r"\d+\s*stops?", ln.lower())) for ln in lines
        ):
            stops_text = "直行"
        else:
            for ln in lines:
                m_st_ja = re.search(r"乗継\s*(\d+)\s*回|(\d+)\s*か所経由", ln)
                if m_st_ja:
                    cnt = m_st_ja.group(1) or m_st_ja.group(2)
                    stops_text = f"経由{cnt}回"
                    break
                m_st_en = re.search(r"(\d+)\s*stops?", ln.lower())
                if m_st_en:
                    stops_text = f"経由{m_st_en.group(1)}回"
                    break

        airline = _extract_airline_from_nrc6(card, route.origin, route.dest)
        lcc_flag = is_lcc_airline(airline) or is_lcc_airline(raw)

        checked_bag: str | None = None
        if re.search(
            r"受託手荷物\s*[:：]?\s*[1-9]\d*|checked bag included|[1-9]\s*checked bag",
            raw,
            re.IGNORECASE,
        ):
            checked_bag = "受託手荷物：込み表示あり"
        elif re.search(r"受託手荷物なし|no checked bag|手荷物追加料金", raw, re.IGNORECASE):
            checked_bag = "受託手荷物：含まれず（別料金）"
        elif lcc_flag:
            checked_bag = "受託手荷物：検索結果カード上に込み表記なし（LCCのため要確認／通常別料金）"

        candidate = FlightObservation(
            route_code=route.code,
            origin=route.origin,
            dest=route.dest,
            city_ja=route.city_ja,
            verified_origin=route.origin,
            verified_dest=route.dest,
            dep_date=dep_date,
            ret_date=ret_date,
            airline=airline,
            lowest_price=card_price,
            currency=currency,
            tax_status=tax_status,  # type: ignore[arg-type]
            typical_low=typ_low,
            typical_high=typ_high,
            typical_currency=currency if typ_low is not None else None,
            typical_source_site=site_name if typ_low is not None else None,
            source_site=site_name,
            search_url=search_url,
            stops_text=stops_text,
            is_lcc=lcc_flag,
            checked_baggage=checked_bag,
        )
        if best_obs is None or candidate.lowest_price < best_obs.lowest_price:
            best_obs = candidate

    if best_obs is not None:
        return best_obs

    return FetchFailure(
        source_site=site_name,
        route_code=route.code,
        category="no_results",
        reason_ja="指定発着空港（近隣空港除く）の確定運賃カードを画面上で確認できず",
        attempted_url=search_url,
    )


async def check_route_secondary_site(
    context: object,
    site_name: str,
    route: RouteSpec,
    dep_date: str,
    ret_date: str,
    timeout_ms: int = 22_000,
) -> FlightObservation | FetchFailure:
    """Open and inspect a secondary flight site for `(route, dep_date, ret_date)`."""
    url = build_secondary_search_url(site_name, route.origin, route.dest, dep_date, ret_date)
    page = await context.new_page()  # type: ignore[attr-defined]
    try:
        resp = await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        status = resp.status if resp else None

        if site_name in ("KAYAK", "Cheapflights", "momondo"):
            try:
                await page.wait_for_selector(".nrc6", timeout=11_000)
                await page.wait_for_timeout(1800)
            except Exception:
                await page.wait_for_timeout(2000)
        else:
            await page.wait_for_timeout(4500)

        title = await page.title()
        body_text = await page.locator("body").inner_text()

        barrier = detect_access_barrier(page.url, title, body_text, status)
        if barrier is not None:
            return FetchFailure(
                source_site=site_name,
                route_code=route.code,
                category=barrier[0],
                reason_ja=barrier[1],
                attempted_url=url,
            )

        if site_name == "catchfrog.ai":
            return FetchFailure(
                source_site="catchfrog.ai",
                route_code=route.code,
                category="unsupported_route",
                reason_ja=(
                    "サイト仕様上、キャッシュされた一覧カード（航空会社・経由・手荷物非表示）のみで"
                    "日付指定の自サイト内検索結果画面が存在しないため除外（予約ボタンは外部サイト Trip.com へ遷移）"
                ),
                attempted_url=url,
            )

        if site_name in ("KAYAK", "Cheapflights", "momondo"):
            cards: list[KayakCardDict] = await page.evaluate(
                """() => {
                    return Array.from(document.querySelectorAll('.nrc6'))
                        .slice(0, 25)
                        .map(el => ({
                            price_text: (el.querySelector('[class*="price-text"]')?.innerText || '').trim(),
                            carrier_text: Array.from(
                                el.querySelectorAll('[class*="carrier"], .J0g6-operator-text, .c5iUd-leg-carrier')
                            ).map(x => (x.innerText || '').trim()).filter(Boolean).join(' / '),
                            raw_text: (el.innerText || '').trim()
                        }))
                        .filter(c => c.price_text && c.raw_text.length > 20);
                }"""
            )
            return _parse_kayak_family_screen(
                site_name, route, dep_date, ret_date, page.url, cards, body_text
            )

        return FetchFailure(
            source_site=site_name,
            route_code=route.code,
            category="no_results",
            reason_ja="実検索結果カードの構造を画面上で確認できず（動的ブロックまたは空画面）",
            attempted_url=url,
        )
    except Exception as exc:
        msg = str(exc)
        if "Timeout" in msg or "timeout" in msg:
            return FetchFailure(
                source_site=site_name,
                route_code=route.code,
                category="timeout",
                reason_ja=f"ページ応答タイムアウト（{timeout_ms // 1000}秒超過）により検索結果画面を開けず",
                attempted_url=url,
            )
        return FetchFailure(
            source_site=site_name,
            route_code=route.code,
            category="parse_error",
            reason_ja=f"通信／画面取得エラー（{type(exc).__name__}）",
            attempted_url=url,
        )
    finally:
        await page.close()
