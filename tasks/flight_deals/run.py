#!/usr/bin/env python3
"""Main orchestrator for daily 15-route international flight deal verification.

Guarantees:
- Opens actual date-specified search result screens via headless Chromium (`browser_helper.py`).
- Strictly forbids cross-site typical price pairing or reusing previous days' results.
- Uses bounded async concurrency + per-site circuit breaker so all 15 routes finish within ~2-3 minutes.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
from datetime import date, datetime
import json
import os
from pathlib import Path
import sys
from typing import Sequence
import zlib

WB_ROOT = Path(__file__).resolve().parents[2]
if str(WB_ROOT) not in sys.path:
    sys.path.insert(0, str(WB_ROOT))
if str(WB_ROOT / "lib") not in sys.path:
    sys.path.insert(0, str(WB_ROOT / "lib"))

from lib.browser_helper import DEFAULT_USER_AGENT, async_open_browser  # noqa: E402
from tasks.flight_deals.config import (  # noqa: E402
    CIRCUIT_BREAKER_CONSECUTIVE_BLOCKS,
    ROUTE_BY_CODE,
    ROUTES_15,
    TARGET_SITES,
    RouteSpec,
)
from tasks.flight_deals.models import JST, FetchFailure, FlightObservation  # noqa: E402
from tasks.flight_deals.reporter import render_report  # noqa: E402
from tasks.flight_deals.sites.google_flights import check_route_google_flights  # noqa: E402
from tasks.flight_deals.sites.other_sites import check_route_secondary_site  # noqa: E402

SECONDARY_SITES: tuple[str, ...] = (
    "KAYAK",
    "Cheapflights",
    "momondo",
    "Priceline",
    "catchfrog.ai",
    "Skyscanner",
)


def load_intrarun_checkpoint(
    checkpoint_file: Path,
    today_jst: date,
) -> tuple[list[FlightObservation], list[FetchFailure], dict[str, tuple[str, str]]]:
    """Load same-run, same-day checkpoint records ONLY (strictly rejects stale prior-day files)."""
    if not checkpoint_file.is_file():
        return ([], [], {})

    observations: list[FlightObservation] = []
    failures: list[FetchFailure] = []
    route_dates: dict[str, tuple[str, str]] = {}

    for raw_line in checkpoint_file.read_text(encoding="utf-8").splitlines():
        if not raw_line.strip():
            continue
        rec = json.loads(raw_line)
        rec_date = str(rec.get("run_date_jst", ""))
        if rec_date != today_jst.isoformat():
            raise RuntimeError(
                f"Refusing to load stale checkpoint from {rec_date} on {today_jst.isoformat()} "
                "(reusing prior days' observations is prohibited)."
            )
        kind = rec.get("kind")
        if kind == "observation":
            obs = FlightObservation.model_validate(rec["payload"])
            observations.append(obs)
        elif kind == "failure":
            fail = FetchFailure.model_validate(rec["payload"])
            failures.append(fail)
        elif kind == "route_dates":
            route_dates[str(rec["route_code"])] = (str(rec["dep_date"]), str(rec["ret_date"]))

    return (observations, failures, route_dates)


def append_checkpoint(checkpoint_file: Path, today_jst: date, entry: dict[str, object]) -> None:
    checkpoint_file.parent.mkdir(parents=True, exist_ok=True)
    payload = {"run_date_jst": today_jst.isoformat(), **entry}
    with checkpoint_file.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, ensure_ascii=False) + "\n")


async def execute_run(
    routes: Sequence[RouteSpec],
    sites: Sequence[str],
    concurrency: int = 2,
    checkpoint_file: Path | None = None,
    today_jst: date | None = None,
) -> tuple[list[FlightObservation], list[FetchFailure]]:
    today = today_jst or datetime.now(JST).date()
    observations: list[FlightObservation] = []
    failures: list[FetchFailure] = []
    route_best_dates: dict[str, tuple[str, str]] = {}

    if checkpoint_file is not None:
        observations, failures, route_best_dates = load_intrarun_checkpoint(checkpoint_file, today)

    done_pairs: set[tuple[str, str]] = {
        (o.source_site, o.route_code) for o in observations
    } | {(f.source_site, f.route_code) for f in failures}

    async with async_open_browser() as browser:
        # Phase A: Google Flights (6-month discovery + verified search screen) with bounded concurrency
        if "Google Flights" in sites:
            sem = asyncio.Semaphore(max(1, concurrency))

            async def _gf_worker(idx: int, r: RouteSpec) -> None:
                if ("Google Flights", r.code) in done_pairs and r.code in route_best_dates:
                    return
                async with sem:
                    if idx > 0:
                        await asyncio.sleep(0.8 * (idx % concurrency))
                    ctx = await browser.new_context(
                        ignore_https_errors=True,
                        user_agent=DEFAULT_USER_AGENT,
                        locale="ja-JP",
                        timezone_id="Asia/Tokyo",
                        viewport={"width": 1440, "height": 950},
                    )
                    try:
                        print(f"[Google Flights] Checking {r.code} ({r.city_ja})...", flush=True)
                        obs, fails, dates_pair = await check_route_google_flights(ctx, r, today)
                        route_best_dates[r.code] = dates_pair
                        if checkpoint_file is not None:
                            append_checkpoint(
                                checkpoint_file,
                                today,
                                {
                                    "kind": "route_dates",
                                    "route_code": r.code,
                                    "dep_date": dates_pair[0],
                                    "ret_date": dates_pair[1],
                                },
                            )
                        if obs is not None:
                            observations.append(obs)
                            if checkpoint_file is not None:
                                append_checkpoint(
                                    checkpoint_file,
                                    today,
                                    {"kind": "observation", "payload": obs.model_dump()},
                                )
                            print(
                                f"  -> OK {r.code}: ¥{int(obs.lowest_price):,} ({obs.dep_date}..{obs.ret_date}, "
                                f"typical={obs.typical_price}, discount={obs.discount_pct}%)",
                                flush=True,
                            )
                        for fl in fails:
                            failures.append(fl)
                            if checkpoint_file is not None:
                                append_checkpoint(
                                    checkpoint_file,
                                    today,
                                    {"kind": "failure", "payload": fl.model_dump()},
                                )
                            print(f"  -> FAIL {r.code}: {fl.reason_ja}", flush=True)
                    finally:
                        await ctx.close()

            await asyncio.gather(*(_gf_worker(i, r) for i, r in enumerate(routes)))

        # Phase B: Secondary sites (run per-site with 2-strike circuit breaker for blocked/timed-out domains)
        active_secondary = [s for s in SECONDARY_SITES if s in sites]

        async def _site_lane(site_name: str) -> None:
            consecutive_blocks = 0
            block_reason_memo = ""
            ctx = await browser.new_context(
                ignore_https_errors=True,
                user_agent=DEFAULT_USER_AGENT,
                locale="ja-JP",
                timezone_id="Asia/Tokyo",
                viewport={"width": 1440, "height": 950},
            )
            try:
                for r in routes:
                    if (site_name, r.code) in done_pairs:
                        continue

                    if site_name == "catchfrog.ai":
                        # Probe catchfrog.ai once on the first route, then apply the verified site-wide structural reason
                        if consecutive_blocks >= 1:
                            fl = FetchFailure(
                                source_site=site_name,
                                route_code=r.code,
                                category="unsupported_route",
                                reason_ja=block_reason_memo,
                            )
                            failures.append(fl)
                            if checkpoint_file is not None:
                                append_checkpoint(
                                    checkpoint_file, today, {"kind": "failure", "payload": fl.model_dump()}
                                )
                            continue

                    if consecutive_blocks >= CIRCUIT_BREAKER_CONSECUTIVE_BLOCKS:
                        fl = FetchFailure(
                            source_site=site_name,
                            route_code=r.code,
                            category="circuit_breaker_skipped",
                            reason_ja=(
                                f"先行{CIRCUIT_BREAKER_CONSECUTIVE_BLOCKS}路線で連続ブロック／タイムアウト"
                                f"（{block_reason_memo}）を確認したため同一ドメイン残路線をスキップ"
                            ),
                        )
                        failures.append(fl)
                        if checkpoint_file is not None:
                            append_checkpoint(
                                checkpoint_file, today, {"kind": "failure", "payload": fl.model_dump()}
                            )
                        continue

                    dep_s, ret_s = route_best_dates.get(r.code) or (
                        date.fromordinal(today.toordinal() + 60).isoformat(),
                        date.fromordinal(today.toordinal() + 60 + r.stay_nights[1]).isoformat(),
                    )
                    print(f"[{site_name}] Checking {r.code} ({dep_s}..{ret_s})...", flush=True)
                    res = await check_route_secondary_site(ctx, site_name, r, dep_s, ret_s)
                    if isinstance(res, FlightObservation):
                        consecutive_blocks = 0
                        observations.append(res)
                        if checkpoint_file is not None:
                            append_checkpoint(
                                checkpoint_file, today, {"kind": "observation", "payload": res.model_dump()}
                            )
                        print(
                            f"  -> OK [{site_name}] {r.code}: {res.currency} {res.lowest_price:,.0f}",
                            flush=True,
                        )
                    else:
                        failures.append(res)
                        if checkpoint_file is not None:
                            append_checkpoint(
                                checkpoint_file, today, {"kind": "failure", "payload": res.model_dump()}
                            )
                        print(f"  -> FAIL [{site_name}] {r.code}: {res.reason_ja}", flush=True)
                        if res.category in ("bot_block", "http_error", "timeout", "login_required", "unsupported_route"):
                            consecutive_blocks += 1
                            block_reason_memo = res.reason_ja
                        else:
                            consecutive_blocks = 0
            finally:
                await ctx.close()

        # Run secondary site lanes with concurrency 2
        sec_sem = asyncio.Semaphore(max(1, concurrency))

        async def _guarded_lane(s: str) -> None:
            async with sec_sem:
                await _site_lane(s)

        await asyncio.gather(*(_guarded_lane(s) for s in active_secondary))

    return (observations, failures)


def save_observations_parquet(observations: Sequence[FlightObservation], today_jst: date) -> Path | None:
    """Append today's verified observations to ~/data/datasets/flight-deals/YYYY-MM-DD.parquet.

    Write-only archive for historical analytics; NEVER read by `run.py` or `reporter.py`.
    """
    if not observations:
        return None
    from lib.duckdb_helper import append_parquet

    rows = [
        {
            **obs.model_dump(),
            "discount_pct": obs.discount_pct,
            "is_deal_40_off": obs.is_deal_40_off,
        }
        for obs in observations
    ]
    return append_parquet(
        "flight-deals",
        rows,
        dedup_keys=["route_code", "source_site", "dep_date", "ret_date"],
        partition_date=today_jst.isoformat(),
    )


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify actual round-trip lowest fares and >=40% deals across 15 NRT/HND routes."
    )
    parser.add_argument(
        "--routes",
        default=None,
        help="Optional comma-separated subset of route codes (e.g. NRT-ICN,NRT-SAI). Default: all 15.",
    )
    parser.add_argument(
        "--sites",
        default=None,
        help="Optional comma-separated subset of site names. Default: all 7 target sites.",
    )
    parser.add_argument(
        "--run-dir",
        default=None,
        help="Optional isolated run directory for intra-run progress.jsonl checkpointing.",
    )
    parser.add_argument(
        "--out",
        default=None,
        help="Optional output Markdown report path.",
    )
    parser.add_argument(
        "--json-out",
        default=None,
        help="Optional structured JSON snapshot output path for dashboard ingestion.",
    )
    parser.add_argument(
        "--bundle-b64-out",
        default=None,
        help="Optional zlib+base64 bundle path containing both report_md and snapshot JSON (~4KB).",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=3,
        help="Browser context concurrency (default: 3).",
    )
    parser.add_argument(
        "--save-parquet",
        action="store_true",
        help="Also archive today's observations to ~/data/datasets/flight-deals/YYYY-MM-DD.parquet.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)

    if args.routes:
        codes = [c.strip().upper() for c in args.routes.split(",") if c.strip()]
        unknown = [c for c in codes if c not in ROUTE_BY_CODE]
        if unknown:
            raise SystemExit(f"Unknown route code(s): {', '.join(unknown)}")
        selected_routes: Sequence[RouteSpec] = [ROUTE_BY_CODE[c] for c in codes]
    else:
        selected_routes = ROUTES_15

    if args.sites:
        wanted = {s.strip().lower() for s in args.sites.split(",") if s.strip()}
        selected_sites = [s for s in TARGET_SITES if s.lower() in wanted]
        if not selected_sites:
            raise SystemExit(f"No matching sites in {args.sites!r}. Valid: {', '.join(TARGET_SITES)}")
    else:
        selected_sites = list(TARGET_SITES)

    today = datetime.now(JST).date()
    ckpt_path: Path | None = None
    if args.run_dir:
        ckpt_path = Path(args.run_dir).expanduser().resolve() / "progress.jsonl"

    observations, failures = asyncio.run(
        execute_run(
            routes=selected_routes,
            sites=selected_sites,
            concurrency=args.concurrency,
            checkpoint_file=ckpt_path,
            today_jst=today,
        )
    )

    now_jst = datetime.now(JST)
    report_md = render_report(observations, failures, routes=selected_routes, executed_at=now_jst)

    if args.out:
        out_path = Path(args.out).expanduser().resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(report_md, encoding="utf-8")
        print(f"[flight_deals] Report written to: {out_path}", flush=True)
    else:
        print("\n" + report_md, flush=True)

    if args.json_out or args.bundle_b64_out:
        confirmed_routes = len({o.route_code for o in observations})
        obs_dicts = [
            {
                **o.model_dump(),
                "discount_pct": o.discount_pct,
                "is_deal_40_off": o.is_deal_40_off,
            }
            for o in observations
        ]
        snapshot = {
            "run_date_jst": today.isoformat(),
            "executed_at_jst": now_jst.strftime("%Y-%m-%d %H:%M:%S JST"),
            "confirmed_route_count": confirmed_routes,
            "total_routes": len(selected_routes),
            "deal_count": sum(1 for o in observations if o.is_deal_40_off),
            "observations": obs_dicts,
            "failures": [f.model_dump() for f in failures],
        }
        if args.json_out:
            json_path = Path(args.json_out).expanduser().resolve()
            json_path.parent.mkdir(parents=True, exist_ok=True)
            json_path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"[flight_deals] JSON snapshot written to: {json_path}", flush=True)
        if args.bundle_b64_out:
            b64_path = Path(args.bundle_b64_out).expanduser().resolve()
            b64_path.parent.mkdir(parents=True, exist_ok=True)
            raw_bundle = json.dumps(
                {"report_md": report_md, "snapshot": snapshot},
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
            encoded = base64.b64encode(zlib.compress(raw_bundle, level=9)).decode("ascii")
            b64_path.write_text(encoded, encoding="utf-8")
            print(
                f"[flight_deals] Compact bundle written to: {b64_path} ({len(encoded)} chars)",
                flush=True,
            )

    if args.save_parquet:
        pq = save_observations_parquet(observations, today)
        if pq:
            print(f"[flight_deals] Archived Parquet partition: {pq}", flush=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
