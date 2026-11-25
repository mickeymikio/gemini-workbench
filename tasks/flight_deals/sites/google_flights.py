"""Google Flights 2-stage adapter: 6-month Price Graph discovery + real search screen verification."""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta
import re

from ..config import MAX_DAYS_AHEAD, MIN_DAYS_AHEAD, RouteSpec, is_lcc_airline
from ..models import JST, FetchFailure, FlightObservation
from ..tfs import build_google_flights_url
from .base import detect_access_barrier, dismiss_google_cookie_consent_if_present

_CALENDAR_PAIR_RE = re.compile(
    r'\\?"(\d{4}-\d{2}-\d{2})\\?",\\?"(\d{4}-\d{2}-\d{2})\\?",\[\[null,(\d+)\]'
)
_TYPICAL_RANGE_JA_RE = re.compile(
    r"通常[^\d￥¥]{0,12}[￥¥]\s*([\d,]+)\s*[～〜~\-－]\s*[￥¥]?\s*([\d,]+)"
)
_TYPICAL_RANGE_EN_RE = re.compile(
    r"usually cost between\s*[¥￥$]\s*([\d,]+)\s*[–\-—to]+\s*[¥￥$]?\s*([\d,]+)",
    re.IGNORECASE,
)
_PRICE_YEN_RE = re.compile(r"(?:[￥¥]\s*([\d,]+)|([\d,]+)\s*円)")
_AIRPORT_PAIR_RE = re.compile(r"\b([A-Z]{3})\s*[–\-—~～]\s*([A-Z]{3})\b")
_LAYOVER_AIRPORT_RE = re.compile(r"\b([A-Z]{3}(?:、\s*[A-Z]{3})*)\s*$")
_SEATS_LEFT_RE = re.compile(r"(残り\s*\d+\s*席|\d+\s*席のみ)")


def parse_typical_range_jpy(text: str) -> tuple[float, float] | None:
    """Extract `(typical_low, typical_high)` in JPY from Google Flights Price Insights text."""
    for pat in (_TYPICAL_RANGE_JA_RE, _TYPICAL_RANGE_EN_RE):
        m = pat.search(text)
        if m:
            low = float(m.group(1).replace(",", ""))
            high = float(m.group(2).replace(",", ""))
            if 0 < low <= high:
                return (low, high)
    return None


def parse_checked_baggage_ja(booking_text: str) -> str:
    """Parse checked baggage inclusion lines from Google Flights' fare summary screen."""
    fee_match = re.search(
        r"1\s*個目の受託手荷物\s*[:：]\s*([￥¥]?\s*[\d,]+\s*(?:円)?(?:\s*[～〜~\-－]\s*[￥¥]?\s*[\d,]+\s*(?:円)?)?)",
        booking_text,
    )
    has_paid = bool(
        re.search(
            r"受託手荷物は\s*1\s*個目から有料|受託手荷物\s*[:：]?\s*別料金|受託手荷物なし",
            booking_text,
        )
    ) or (fee_match is not None)
    free_match = re.search(r"受託手荷物は\s*(\d+)\s*個まで無料|受託手荷物\s*(\d+)\s*個無料", booking_text)
    unknown_info = "手荷物料金の情報が提供されません" in booking_text

    if has_paid and free_match:
        return "受託手荷物：片道のみ無料・片道は有料（往復混在）"
    if fee_match:
        fee_str = re.sub(r"\s+", "", fee_match.group(1))
        return f"受託手荷物：含まれず（1個目 {fee_str} 別料金）"
    if has_paid:
        return "受託手荷物：含まれず（1個目から別料金）"
    if free_match:
        cnt = free_match.group(1) or free_match.group(2)
        return f"受託手荷物：含まれる（{cnt}個まで無料）"
    if unknown_info:
        return "受託手荷物：画面上に「手荷物料金の情報が提供されません」と表示（要航空会社規定確認）"
    return "受託手荷物：画面上に明記なし"


def parse_flight_card_fields(
    card_text: str,
    aria_label: str,
    expected_origin: str,
    expected_dest: str,
) -> dict[str, object] | None:
    """Parse an outbound/return `li.pIav2d` card and strictly enforce exact IATA airport codes."""
    lines = [ln.strip().replace("\xa0", " ") for ln in card_text.splitlines() if ln.strip()]

    # 1. Verify exact origin & destination IATA codes on this card
    found_orig: str | None = None
    found_dest: str | None = None
    for ln in lines:
        m_pair = _AIRPORT_PAIR_RE.search(ln)
        if m_pair:
            found_orig, found_dest = m_pair.group(1).upper(), m_pair.group(2).upper()
            break

    if not found_orig or not found_dest:
        return None
    if found_orig != expected_origin.upper() or found_dest != expected_dest.upper():
        return None

    # 2. Price in JPY
    price_val: float | None = None
    m_aria_price = re.search(r"合計金額\s*([\d,]+)\s*円|([\d,]+)\s*円", aria_label)
    if m_aria_price:
        raw_p = m_aria_price.group(1) or m_aria_price.group(2)
        price_val = float(raw_p.replace(",", ""))
    else:
        for ln in reversed(lines):
            m_p = _PRICE_YEN_RE.search(ln)
            if m_p:
                raw_p = m_p.group(1) or m_p.group(2)
                price_val = float(raw_p.replace(",", ""))
                break
    if not price_val or price_val <= 0:
        return None

    # 3. Airline name
    airline = ""
    m_air = re.search(r"。\s*(.+?)\s*が運航する", aria_label)
    if m_air:
        airline = m_air.group(1).strip()
    else:
        # In card lines, airline usually immediately precedes duration (`X時間 Y分`)
        for i, ln in enumerate(lines):
            if "時間" in ln and i > 0:
                airline = lines[i - 1]
                break
    airline = re.sub(r"航空会社:\s*", "／運航:", airline).strip() or "航空会社名取得不可"

    # 4. Stops & layover airport codes
    stops_text = "直行"
    for i, ln in enumerate(lines):
        if "直行" in ln:
            stops_text = "直行"
            break
        m_stop = re.search(r"(\d+)\s*か所経由", ln)
        if m_stop:
            n_stops = m_stop.group(1)
            via_code = ""
            if i + 1 < len(lines):
                nxt = lines[i + 1]
                m_via = re.search(r"\b([A-Z]{3}(?:、\s*[A-Z]{3})*)\b", nxt)
                if m_via:
                    via_code = m_via.group(1)
                elif "別の空港" in nxt:
                    via_code = "空港移動あり"
            stops_text = f"経由{n_stops}回（{via_code}）" if via_code else f"経由{n_stops}回"
            break

    # 5. Seats left if present
    seats_left: str | None = None
    m_seats = _SEATS_LEFT_RE.search(card_text) or _SEATS_LEFT_RE.search(aria_label)
    if m_seats:
        seats_left = m_seats.group(1)

    return {
        "origin": found_orig,
        "dest": found_dest,
        "price": price_val,
        "airline": airline,
        "stops_text": stops_text,
        "seats_remaining": seats_left,
    }


async def _load_gf_page_with_retry(page: object, url: str, timeout_ms: int = 30_000) -> int | None:
    """Navigate to a Google Flights URL, handle cookie consent, and reload once on empty cold RPC."""
    resp = await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)  # type: ignore[attr-defined]
    status = resp.status if resp else None
    await dismiss_google_cookie_consent_if_present(page)
    await page.wait_for_timeout(4200)  # type: ignore[attr-defined]
    if await page.locator("li.pIav2d").count() == 0:  # type: ignore[attr-defined]
        body_now = await page.locator("body").inner_text()  # type: ignore[attr-defined]
        title_now = await page.title()  # type: ignore[attr-defined]
        if detect_access_barrier(page.url, title_now, body_now, status) is None:  # type: ignore[attr-defined]
            resp2 = await page.reload(wait_until="domcontentloaded", timeout=timeout_ms)  # type: ignore[attr-defined]
            if resp2:
                status = resp2.status
            await page.wait_for_timeout(4500)  # type: ignore[attr-defined]
    return status


async def discover_cheapest_dates_6m(
    context: object,
    route: RouteSpec,
    today_jst: date,
    top_k: int = 2,
) -> list[tuple[str, str, float]]:
    """Scan ~6 months (+7..+180 days) via Google Flights Price Graph / Calendar Grid RPCs.

    Returns up to `top_k` `(dep_date, ret_date, calendar_price_jpy)` candidates sorted cheapest first.
    """
    min_dep = today_jst + timedelta(days=MIN_DAYS_AHEAD)
    max_dep = today_jst + timedelta(days=MAX_DAYS_AHEAD)
    allowed_nights = set(route.stay_nights)
    mid_nights = route.stay_nights[len(route.stay_nights) // 2]

    collected: dict[tuple[str, str], float] = {}
    raw_rpc_chunks: list[str] = []

    page = await context.new_page()  # type: ignore[attr-defined]

    async def _capture_rpc(resp: object) -> None:
        r_url = getattr(resp, "url", "")
        if "GetCalendarGraph" in r_url or "GetCalendarGrid" in r_url:
            try:
                txt = await resp.text()  # type: ignore[attr-defined]
                raw_rpc_chunks.append(txt)
            except Exception:
                pass

    page.on("response", lambda r: asyncio.ensure_future(_capture_rpc(r)))

    try:
        # Three 60-day windows cover [today+7 .. today+180] completely:
        # seed +14 -> [+7..+66], seed +74 -> [+67..+126], seed +134 -> [+127..+186]
        seed_offsets = (14, 74, 134)
        for idx, offset in enumerate(seed_offsets):
            seed_dep = today_jst + timedelta(days=offset)
            if seed_dep > max_dep:
                continue
            seed_ret = seed_dep + timedelta(days=mid_nights)
            url = build_google_flights_url(
                route.origin, route.dest, seed_dep.isoformat(), seed_ret.isoformat()
            )
            await page.goto(url, wait_until="domcontentloaded", timeout=25_000)
            if idx == 0:
                await dismiss_google_cookie_consent_if_present(page)
            graph_btn = page.get_by_role("button", name=re.compile("料金グラフ"))
            try:
                await graph_btn.first.wait_for(state="visible", timeout=6_000)
            except Exception:
                await page.wait_for_timeout(2000)

            if await graph_btn.count() > 0:
                try:
                    async with page.expect_response(
                        lambda r: "GetCalendarGraph" in r.url, timeout=5_000
                    ) as resp_info:
                        await graph_btn.first.click(timeout=2_500)
                    cal_resp = await resp_info.value
                    raw_rpc_chunks.append(await cal_resp.text())
                except Exception:
                    await page.wait_for_timeout(1200)
    finally:
        await page.close()

    for chunk in raw_rpc_chunks:
        for dep_s, ret_s, price_s in _CALENDAR_PAIR_RE.findall(chunk):
            try:
                d1 = date.fromisoformat(dep_s)
                d2 = date.fromisoformat(ret_s)
                p = float(price_s)
            except ValueError:
                continue
            nights = (d2 - d1).days
            if d1 < min_dep or d1 > max_dep:
                continue
            if nights not in allowed_nights and not (
                min(allowed_nights) <= nights <= max(allowed_nights)
            ):
                continue
            if p <= 0:
                continue
            key = (dep_s, ret_s)
            if key not in collected or p < collected[key]:
                collected[key] = p

    ranked = sorted(
        [(dep_s, ret_s, p) for (dep_s, ret_s), p in collected.items()],
        key=lambda x: (x[2], x[0]),
    )
    if ranked:
        return ranked[:top_k]

    # Deterministic fallback probe dates if CalendarGraph RPC yielded 0 items
    fb1_dep = today_jst + timedelta(days=60)
    fb2_dep = today_jst + timedelta(days=110)
    return [
        (fb1_dep.isoformat(), (fb1_dep + timedelta(days=mid_nights)).isoformat(), 0.0),
        (fb2_dep.isoformat(), (fb2_dep + timedelta(days=mid_nights)).isoformat(), 0.0),
    ][:top_k]


async def verify_google_flights_dates(
    context: object,
    route: RouteSpec,
    dep_date: str,
    ret_date: str,
) -> FlightObservation | FetchFailure:
    """Open the actual date-embedded Google Flights search screen and extract verified metrics."""
    search_url = build_google_flights_url(route.origin, route.dest, dep_date, ret_date)
    page = await context.new_page()  # type: ignore[attr-defined]
    try:
        status = await _load_gf_page_with_retry(page, search_url)
        title = await page.title()
        body_text = await page.locator("body").inner_text()

        barrier = detect_access_barrier(page.url, title, body_text, status)
        if barrier is not None:
            return FetchFailure(
                source_site="Google Flights",
                route_code=route.code,
                category=barrier[0],
                reason_ja=barrier[1],
                attempted_url=search_url,
            )

        # Expand Price Insights ("料金の推移を表示") if collapsed
        typical_range = parse_typical_range_jpy(body_text)
        if typical_range is None:
            exp_btn = page.locator("div.TesKhb button")
            if await exp_btn.count() > 0:
                try:
                    await exp_btn.first.click(timeout=2500)
                    await page.wait_for_timeout(1200)
                    body_text = await page.locator("body").inner_text()
                    typical_range = parse_typical_range_jpy(body_text)
                except Exception:
                    pass

        tax_status: str = "税込表記確認不可"
        if "必要な税金と諸費用が含まれます" in body_text or "税金と手数料込み" in body_text:
            tax_status = "税込"
        elif "税別" in body_text or "税金・諸費用別" in body_text:
            tax_status = "税別"

        cards = page.locator("li.pIav2d")
        card_count = await cards.count()
        if card_count == 0:
            return FetchFailure(
                source_site="Google Flights",
                route_code=route.code,
                category="no_results",
                reason_ja=f"指定日程（{dep_date}〜{ret_date}）の検索結果画面に該当便なし",
                attempted_url=search_url,
            )

        valid_cards: list[tuple[int, dict[str, object]]] = []
        for idx in range(min(card_count, 25)):
            c_loc = cards.nth(idx)
            c_txt = await c_loc.inner_text()
            aria_el = c_loc.locator('[aria-label*="フライトを選択"]')
            c_aria = (
                (await aria_el.first.get_attribute("aria-label")) or ""
                if await aria_el.count() > 0
                else ""
            )
            parsed = parse_flight_card_fields(c_txt, c_aria, route.origin, route.dest)
            if parsed is not None:
                valid_cards.append((idx, parsed))

        if not valid_cards:
            return FetchFailure(
                source_site="Google Flights",
                route_code=route.code,
                category="airport_mismatch",
                reason_ja=f"検索結果が近隣空港便のみで {route.origin}→{route.dest} 厳密一致便を確認できず",
                attempted_url=search_url,
            )

        best_idx, best = min(valid_cards, key=lambda item: float(item[1]["price"]))  # type: ignore[arg-type]
        confirmed_price = float(best["price"])  # type: ignore[arg-type]
        airline = str(best["airline"])
        stops_text = str(best["stops_text"])
        seats_rem = str(best["seats_remaining"]) if best.get("seats_remaining") else None
        lcc_flag = is_lcc_airline(airline)
        checked_baggage: str | None = None
        ret_orig_verified: str | None = None
        ret_dest_verified: str | None = None

        # Click through Outbound -> Return -> Fare Summary screen inside Google Flights (view-only)
        # whenever LCC baggage must be verified OR typical_range wasn't yet visible.
        if lcc_flag or typical_range is None:
            try:
                out_card = cards.nth(best_idx)
                await out_card.locator("button").last.click(timeout=2500)
                await page.wait_for_timeout(600)
                sel_out = out_card.get_by_role("button", name="フライトを選択")
                if await sel_out.count() > 0:
                    await sel_out.first.click(timeout=3000)
                    await page.wait_for_timeout(3200)

                    ret_cards = page.locator("li.pIav2d")
                    ret_cnt = await ret_cards.count()
                    chosen_ret_idx: int | None = None
                    chosen_ret_parsed: dict[str, object] | None = None
                    for r_i in range(min(ret_cnt, 15)):
                        r_loc = ret_cards.nth(r_i)
                        r_txt = await r_loc.inner_text()
                        r_aria_el = r_loc.locator('[aria-label*="フライトを選択"]')
                        r_aria = (
                            (await r_aria_el.first.get_attribute("aria-label")) or ""
                            if await r_aria_el.count() > 0
                            else ""
                        )
                        r_parsed = parse_flight_card_fields(
                            r_txt, r_aria, route.dest, route.origin
                        )
                        if r_parsed is not None:
                            if (
                                chosen_ret_parsed is None
                                or float(r_parsed["price"]) < float(chosen_ret_parsed["price"])  # type: ignore[arg-type]
                            ):
                                chosen_ret_idx = r_i
                                chosen_ret_parsed = r_parsed

                    if chosen_ret_idx is not None and chosen_ret_parsed is not None:
                        ret_orig_verified = str(chosen_ret_parsed["origin"])
                        ret_dest_verified = str(chosen_ret_parsed["dest"])
                        confirmed_price = float(chosen_ret_parsed["price"])  # type: ignore[arg-type]
                        ret_air = str(chosen_ret_parsed["airline"])
                        if ret_air and ret_air not in airline and ret_air != "航空会社名取得不可":
                            airline = f"{airline} ／ 復路：{ret_air}"
                            lcc_flag = is_lcc_airline(airline)

                        r_card = ret_cards.nth(chosen_ret_idx)
                        await r_card.locator("button").last.click(timeout=2500)
                        await page.wait_for_timeout(600)
                        sel_ret = r_card.get_by_role("button", name="フライトを選択")
                        if await sel_ret.count() > 0:
                            await sel_ret.first.click(timeout=3000)
                            try:
                                await page.locator("text=/受託手荷物|手荷物料金/").first.wait_for(
                                    state="visible", timeout=6500
                                )
                            except Exception:
                                await page.wait_for_timeout(4200)
                            booking_text = await page.locator("body").inner_text()
                            checked_baggage = parse_checked_baggage_ja(booking_text)
                            if typical_range is None:
                                typical_range = parse_typical_range_jpy(booking_text)
                            if tax_status == "税込表記確認不可" and "必要な税金と諸費用が含まれます" in booking_text:
                                tax_status = "税込"
            except Exception:
                if lcc_flag and not checked_baggage:
                    checked_baggage = "受託手荷物：詳細画面展開時に確認できず（LCCのため要確認）"

        typ_low = typical_range[0] if typical_range else None
        typ_high = typical_range[1] if typical_range else None

        return FlightObservation(
            route_code=route.code,
            origin=route.origin,
            dest=route.dest,
            city_ja=route.city_ja,
            verified_origin=str(best["origin"]),
            verified_dest=str(best["dest"]),
            verified_return_origin=ret_orig_verified,
            verified_return_dest=ret_dest_verified,
            dep_date=dep_date,
            ret_date=ret_date,
            airline=airline,
            lowest_price=confirmed_price,
            currency="JPY",
            tax_status=tax_status,  # type: ignore[arg-type]
            typical_low=typ_low,
            typical_high=typ_high,
            typical_currency="JPY" if typical_range else None,
            typical_source_site="Google Flights" if typical_range else None,
            source_site="Google Flights",
            search_url=search_url,
            stops_text=stops_text,
            is_lcc=lcc_flag,
            checked_baggage=checked_baggage,
            seats_remaining=seats_rem,
        )
    except Exception as exc:
        msg = str(exc)
        if "Timeout" in msg or "timeout" in msg:
            return FetchFailure(
                source_site="Google Flights",
                route_code=route.code,
                category="timeout",
                reason_ja="Google Flights 検索結果画面の読み込みタイムアウト",
                attempted_url=search_url,
            )
        return FetchFailure(
            source_site="Google Flights",
            route_code=route.code,
            category="parse_error",
            reason_ja=f"画面解析エラー（{type(exc).__name__}）",
            attempted_url=search_url,
        )
    finally:
        await page.close()


async def check_route_google_flights(
    context: object,
    route: RouteSpec,
    today_jst: date | None = None,
) -> tuple[FlightObservation | None, list[FetchFailure], tuple[str, str]]:
    """Run full 6-month Stage 1 + Top-K Stage 2 verification for one route on Google Flights.

    Also returns the best `(dep_date, ret_date)` pair so secondary sites without a 6-month
    calendar can probe an actual date-specified search screen on the same route.
    """
    today = today_jst or datetime.now(JST).date()
    candidates = await discover_cheapest_dates_6m(context, route, today, top_k=2)
    best_dates = (candidates[0][0], candidates[0][1])

    verified_obs: list[FlightObservation] = []
    failures: list[FetchFailure] = []

    for idx, (dep_s, ret_s, cal_price) in enumerate(candidates):
        res = await verify_google_flights_dates(context, route, dep_s, ret_s)
        if isinstance(res, FlightObservation):
            verified_obs.append(res)
            # If #1 reproduced closely (within 15% of calendar teaser) or no #2 has cheaper teaser, stop early!
            if idx == 0 and len(candidates) > 1:
                next_cal = candidates[1][2]
                if cal_price > 0 and res.lowest_price <= cal_price * 1.15:
                    if next_cal == 0 or res.lowest_price <= next_cal:
                        break
        else:
            failures.append(res)
            if res.category == "bot_block":
                break

    if verified_obs:
        winner = min(verified_obs, key=lambda o: o.lowest_price)
        return (winner, [], (winner.dep_date, winner.ret_date))

    return (None, failures, best_dates)
