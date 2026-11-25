"""Markdown report generator strictly matching the user's 4-section specification."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Sequence

from .config import ROUTES_15, RouteSpec
from .models import JST, FetchFailure, FlightObservation, format_date_ja, format_money

# Used ONLY for ordering/selecting the single cheapest reference row per route when
# one site reports JPY and another reports USD/KRW. Never used for discount math or display.
_RANKING_FX_TO_JPY: dict[str, float] = {
    "JPY": 1.0,
    "USD": 155.0,
    "KRW": 0.11,
    "EUR": 163.0,
}


def _ranking_jpy(obs: FlightObservation) -> float:
    rate = _RANKING_FX_TO_JPY.get(obs.currency.upper(), 1.0)
    return obs.lowest_price * rate


def _format_typical(obs: FlightObservation) -> str:
    if obs.typical_price is None or obs.typical_currency is None:
        return "同サイト上に表示なし"
    base = format_money(obs.typical_price, obs.typical_currency)
    if (
        obs.typical_low is not None
        and obs.typical_high is not None
        and abs(obs.typical_high - obs.typical_low) >= 1e-6
    ):
        low_s = format_money(obs.typical_low, obs.typical_currency).split("（")[0]
        high_s = format_money(obs.typical_high, obs.typical_currency).split("（")[0]
        return f"{base}［画面表示レンジ {low_s}〜{high_s} の中央値］"
    return base


def _format_remarks(obs: FlightObservation) -> str:
    parts: list[str] = [obs.stops_text]
    if obs.is_lcc:
        bag = obs.checked_baggage or "受託手荷物：画面上に明記なし"
        if not bag.startswith("受託手荷物"):
            bag = f"受託手荷物：{bag}"
        parts.append(f"LCC（{bag}）")
    elif obs.checked_baggage:
        bag = obs.checked_baggage
        if not bag.startswith("受託手荷物"):
            bag = f"受託手荷物：{bag}"
        parts.append(bag)
    if obs.seats_remaining:
        parts.append(obs.seats_remaining)
    if obs.extra_note:
        parts.append(obs.extra_note)
    return " ／ ".join(p for p in parts if p)


def render_report(
    observations: Sequence[FlightObservation],
    failures: Sequence[FetchFailure],
    routes: Sequence[RouteSpec] = ROUTES_15,
    executed_at: datetime | None = None,
) -> str:
    """Render the complete 4-section Japanese flight deal report."""
    now_jst = (executed_at or datetime.now(JST)).astimezone(JST)
    now_str = f"{format_date_ja(now_jst.date().isoformat())} {now_jst.strftime('%H:%M:%S')} JST"

    target_codes = {r.code for r in routes}
    valid_obs = [o for o in observations if o.route_code in target_codes]

    obs_by_route: dict[str, list[FlightObservation]] = defaultdict(list)
    for obs in valid_obs:
        obs_by_route[obs.route_code].append(obs)

    confirmed_route_count = sum(1 for r in routes if obs_by_route.get(r.code))
    deals = sorted(
        [o for o in valid_obs if o.is_deal_40_off],
        key=lambda o: (-(o.discount_pct or 0.0), _ranking_jpy(o)),
    )

    lines: list[str] = []

    # Section 1: Summary
    lines.append("■ 実行サマリー")
    lines.append(f"- 確認日時（JST）：{now_str}")
    lines.append(f"- 確認できた路線数：{confirmed_route_count} ／ {len(routes)}")
    lines.append(f"- 40%以上オフのディール件数：{len(deals)}件")
    lines.append("")

    # Section 2: Deals (>= 40% off, descending discount)
    lines.append("■ ディール（40%以上オフのみ、割引率の大きい順）")
    if not deals:
        lines.append(
            "- 該当なし（今回の実画面確認では、同一サイトの通常価格比40%以上オフとなる運賃はありませんでした）"
        )
    else:
        for idx, d in enumerate(deals, start=1):
            lines.append(f"【{idx}】 {d.origin}→{d.dest}（{d.city_ja}） — {d.discount_pct:.1f}%オフ")
            lines.append(f"- 路線：{d.origin}→{d.dest}（{d.city_ja}）")
            lines.append(
                f"- 出発日・帰国日：{format_date_ja(d.dep_date)} 〜 {format_date_ja(d.ret_date)}"
            )
            lines.append(f"- 航空会社：{d.airline}")
            lines.append(
                f"- 確認した往復最安値と通貨：{format_money(d.lowest_price, d.currency)}（{d.tax_status}）"
            )
            lines.append(f"- 通常価格と通貨：{_format_typical(d)}")
            lines.append(f"- 割引率（%）：{d.discount_pct:.1f}%")
            lines.append(f"- 出典サイト名：{d.source_site}")
            lines.append(f"- 実際に開いた検索結果画面のURL：{d.search_url}")
            lines.append(f"- 備考：{_format_remarks(d)}")
            lines.append("")
    if not deals:
        lines.append("")

    # Section 3: Reference observations (1 cheapest per route, even if < 40% off)
    lines.append("■ 参考観測（40%未満でも、各路線の最安は1件ずつ）")
    for r in routes:
        candidates = obs_by_route.get(r.code, [])
        if not candidates:
            lines.append(f"- {r.label_ja}｜取得できた実検索結果なし")
            continue
        best = min(candidates, key=_ranking_jpy)
        disc_note = (
            f"（通常価格比 {best.discount_pct:.1f}%オフ）"
            if best.discount_pct is not None and best.discount_pct > 0
            else (
                f"（通常価格比 +{abs(best.discount_pct):.1f}%高）"
                if best.discount_pct is not None and best.discount_pct < 0
                else (
                    "（通常価格と同水準 0.0%）"
                    if best.discount_pct == 0.0
                    else "（同サイトに通常価格表示なし）"
                )
            )
        )
        lines.append(
            f"- {r.label_ja}｜{format_date_ja(best.dep_date)}〜{format_date_ja(best.ret_date)}"
            f"｜{format_money(best.lowest_price, best.currency)}（{best.tax_status}）"
            f"｜{best.source_site}{disc_note}"
        )
    lines.append("")

    # Section 4: Unfetchable items
    lines.append("■ 取得できなかったもの")
    if not failures:
        lines.append("- なし（全対象サイト・全路線を取得完了）")
    else:
        grouped: dict[tuple[str, str], list[str]] = defaultdict(list)
        site_order: list[tuple[str, str]] = []
        for f in failures:
            key = (f.source_site, f.reason_ja)
            if key not in grouped:
                site_order.append(key)
            if f.route_code not in grouped[key]:
                grouped[key].append(f.route_code)

        for site, reason in site_order:
            r_list = grouped[(site, reason)]
            if len(r_list) == len(routes):
                route_desc = f"全{len(routes)}路線（{', '.join(r_list)}）"
            else:
                route_desc = f"{len(r_list)}路線（{', '.join(r_list)}）"
            lines.append(f"- {site} ／ {route_desc}：{reason}")

    return "\n".join(lines).rstrip() + "\n"
