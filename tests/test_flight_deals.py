"""Comprehensive stdlib unittest suite for tasks.flight_deals."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
import tempfile
import unittest

from pydantic import ValidationError

from tasks.flight_deals.config import ROUTES_15, ROUTE_BY_CODE, is_lcc_airline
from tasks.flight_deals.models import JST, FetchFailure, FlightObservation, format_date_ja
from tasks.flight_deals.reporter import render_report
from tasks.flight_deals.run import append_checkpoint, load_intrarun_checkpoint
from tasks.flight_deals.sites.base import detect_access_barrier
from tasks.flight_deals.sites.google_flights import (
    parse_checked_baggage_ja,
    parse_flight_card_fields,
    parse_typical_range_jpy,
)
from tasks.flight_deals.sites.other_sites import _parse_kayak_family_screen
from tasks.flight_deals.tfs import build_google_flights_url, encode_roundtrip_tfs


class TestConfigAndTfs(unittest.TestCase):
    def test_fifteen_routes_complete(self) -> None:
        self.assertEqual(len(ROUTES_15), 15)
        codes = [r.code for r in ROUTES_15]
        for expected in (
            "NRT-ICN",
            "HND-GMP",
            "NRT-TPE",
            "HND-TSA",
            "NRT-HKG",
            "NRT-BKK",
            "HND-SIN",
            "NRT-HNL",
            "HND-LAX",
            "NRT-SGN",
            "NRT-SYD",
            "NRT-HAN",
            "NRT-MNL",
            "NRT-SAI",
            "NRT-DAD",
        ):
            self.assertIn(expected, codes)

    def test_tfs_supports_sai_and_validates_dates(self) -> None:
        url = build_google_flights_url("NRT", "SAI", "2027-02-10", "2027-02-14")
        self.assertTrue(url.startswith("https://www.google.com/travel/flights/search?tfs="))
        self.assertIn("curr=JPY", url)
        with self.assertRaises(ValueError):
            encode_roundtrip_tfs("NRT", "ICN", "2027-02-14", "2027-02-10")
        with self.assertRaises(ValueError):
            encode_roundtrip_tfs("TYO1", "ICN", "2027-02-10", "2027-02-14")

    def test_lcc_detection(self) -> None:
        self.assertTrue(is_lcc_airline("ZIPAIR Tokyo"))
        self.assertTrue(is_lcc_airline("ベトジェット・エア"))
        self.assertTrue(is_lcc_airline("タイ・エアアジアX、タイ・エアアジア"))
        self.assertTrue(is_lcc_airline("Scoot"))
        self.assertFalse(is_lcc_airline("JAL"))
        self.assertFalse(is_lcc_airline("ANA"))


class TestObservationValidation(unittest.TestCase):
    def test_midpoint_typical_and_40_pct_boundary(self) -> None:
        obs = FlightObservation(
            route_code="NRT-ICN",
            origin="NRT",
            dest="ICN",
            city_ja="ソウル仁川",
            verified_origin="NRT",
            verified_dest="ICN",
            dep_date="2027-02-10",
            ret_date="2027-02-14",
            airline="ZIPAIR",
            lowest_price=36000,
            currency="JPY",
            tax_status="税込",
            typical_low=48000,
            typical_high=72000,
            typical_currency="JPY",
            typical_source_site="Google Flights",
            source_site="Google Flights",
            search_url="https://www.google.com/travel/flights/search?tfs=abc",
            stops_text="直行",
            is_lcc=True,
            checked_baggage="受託手荷物：含まれず（1個目から別料金）",
        )
        self.assertEqual(obs.typical_price, 60000.0)
        self.assertEqual(obs.discount_pct, 40.0)
        self.assertTrue(obs.is_deal_40_off)

        obs_below = obs.model_copy(update={"lowest_price": 36100})
        self.assertFalse(obs_below.is_deal_40_off)

    def test_cross_site_and_cross_currency_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            FlightObservation(
                route_code="NRT-ICN",
                origin="NRT",
                dest="ICN",
                city_ja="ソウル仁川",
                verified_origin="NRT",
                verified_dest="ICN",
                dep_date="2027-02-10",
                ret_date="2027-02-14",
                airline="Peach",
                lowest_price=25000,
                currency="JPY",
                typical_price=50000,
                typical_currency="JPY",
                typical_source_site="Google Flights",
                source_site="KAYAK",
                search_url="https://www.kayak.co.jp/flights/NRT-ICN/2027-02-10/2027-02-14",
                stops_text="直行",
            )
        with self.assertRaises(ValidationError):
            FlightObservation(
                route_code="NRT-ICN",
                origin="NRT",
                dest="ICN",
                city_ja="ソウル仁川",
                verified_origin="NRT",
                verified_dest="ICN",
                dep_date="2027-02-10",
                ret_date="2027-02-14",
                airline="Peach",
                lowest_price=200,
                currency="USD",
                typical_price=50000,
                typical_currency="JPY",
                typical_source_site="Cheapflights",
                source_site="Cheapflights",
                search_url="https://www.cheapflights.com/flight-search/NRT-ICN/2027-02-10/2027-02-14",
                stops_text="直行",
            )

    def test_coterminal_airport_mismatch_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            FlightObservation(
                route_code="HND-GMP",
                origin="HND",
                dest="GMP",
                city_ja="ソウル金浦",
                verified_origin="NRT",
                verified_dest="GMP",
                dep_date="2027-02-10",
                ret_date="2027-02-14",
                airline="ANA",
                lowest_price=40000,
                currency="JPY",
                source_site="Google Flights",
                search_url="https://www.google.com/travel/flights/search?tfs=xyz",
                stops_text="直行",
            )


class TestGoogleFlightsAndKayakParsers(unittest.TestCase):
    def test_parse_typical_range_and_baggage(self) -> None:
        rng = parse_typical_range_jpy(
            "ソウル行きの同様の旅行における最低価格は、通常 ￥36,000～58,000 の範囲になります。"
        )
        self.assertEqual(rng, (36000.0, 58000.0))

        self.assertEqual(
            parse_checked_baggage_ja("機内持ち込み手荷物 1 個は無料\n受託手荷物は 1 個目から有料"),
            "受託手荷物：含まれず（1個目から別料金）",
        )
        self.assertEqual(
            parse_checked_baggage_ja("受託手荷物は 2 個まで無料"),
            "受託手荷物：含まれる（2個まで無料）",
        )
        self.assertEqual(
            parse_checked_baggage_ja("受託手荷物は 1 個目から有料\n受託手荷物は 1 個まで無料"),
            "受託手荷物：片道のみ無料・片道は有料（往復混在）",
        )

    def test_parse_flight_card_enforces_exact_airports(self) -> None:
        sai_card = "\n".join(
            [
                "9:30",
                "–",
                "18:05",
                "ベトジェット・エア",
                "10時間 35分",
                "NRT–SAI",
                "1 か所経由",
                "2時間 20分 HAN",
                "￥132,801",
                "往復",
            ]
        )
        sai_aria = (
            "往復の合計金額 132801 円～。 ベトジェット・エア が運航する経由地 1 か所のフライト。"
            " 成田国際空港発、シェムリアップ国際空港着。 フライトを選択"
        )
        parsed = parse_flight_card_fields(sai_card, sai_aria, "NRT", "SAI")
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed["price"], 132801.0)
        self.assertEqual(parsed["airline"], "ベトジェット・エア")
        self.assertEqual(parsed["stops_text"], "経由1回（HAN）")

        # Must reject NRT-LAX card when HND-LAX is requested
        nrt_lax_card = "17:00\n–\n10:00\nZIPAIR\n9時間\nNRT–LAX\n直行便\n￥111,709\n往復"
        self.assertIsNone(parse_flight_card_fields(nrt_lax_card, "", "HND", "LAX"))

    def test_kayak_parser_never_fabricates_typical_price(self) -> None:
        route = ROUTE_BY_CODE["NRT-ICN"]
        card = {
            "price_text": "¥31,630",
            "carrier_text": "ZIPAIR",
            "raw_text": "検索結果が完全に読み込まれたら、フライトを比較します。\n09:55 – 12:35\nNRT成田国際空港\n-\nICN仁川国際空港\n直行便\nZIPAIR\n¥31,630",
        }
        res = _parse_kayak_family_screen(
            "KAYAK",
            route,
            "2027-02-10",
            "2027-02-14",
            "https://www.kayak.co.jp/flights/NRT-ICN/2027-02-10/2027-02-14?sort=price_a",
            [card],
            "往復 JPY 税金・手数料込み " + card["raw_text"],
        )
        self.assertIsInstance(res, FlightObservation)
        assert isinstance(res, FlightObservation)
        self.assertEqual(res.lowest_price, 31630.0)
        self.assertEqual(res.airline, "ZIPAIR")
        self.assertIsNone(res.typical_price)
        self.assertIsNone(res.discount_pct)
        self.assertTrue(res.is_lcc)

        # Must reject co-terminal substitution (NRT leg inside an HND-LAX search)
        bad_coterm = {
            "price_text": "$890",
            "carrier_text": "ZIPAIR",
            "raw_text": "HND - LAX\nLAX - NRT\n$890",
        }
        res_bad = _parse_kayak_family_screen(
            "Cheapflights",
            ROUTE_BY_CODE["HND-LAX"],
            "2027-05-10",
            "2027-05-16",
            "https://www.cheapflights.com/flight-search/HND-LAX/2027-05-10/2027-05-16?sort=price_a",
            [bad_coterm],
            bad_coterm["raw_text"],
        )
        self.assertIsInstance(res_bad, FetchFailure)


class TestCheckpointAndReporter(unittest.TestCase):
    def test_stale_prior_day_checkpoint_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            ckpt = Path(td) / "progress.jsonl"
            append_checkpoint(
                ckpt,
                date(2026, 11, 24),
                {"kind": "route_dates", "route_code": "NRT-ICN", "dep_date": "2027-02-10", "ret_date": "2027-02-14"},
            )
            with self.assertRaises(RuntimeError):
                load_intrarun_checkpoint(ckpt, date(2026, 11, 25))

    def test_barrier_and_report_rendering(self) -> None:
        res1 = detect_access_barrier(
            "https://www.priceline.com/m/fly/search/...",
            "Access to this page has been denied",
            "続行する前に... 長押ししてあなたが人間であることを確認します。",
            403,
        )
        self.assertIsNotNone(res1)
        assert res1 is not None
        self.assertEqual(res1[0], "bot_block")

        d1 = FlightObservation(
            route_code="NRT-ICN",
            origin="NRT",
            dest="ICN",
            city_ja="ソウル仁川",
            verified_origin="NRT",
            verified_dest="ICN",
            dep_date="2027-02-10",
            ret_date="2027-02-14",
            airline="チェジュ航空",
            lowest_price=24000,
            currency="JPY",
            tax_status="税込",
            typical_low=45000,
            typical_high=55000,
            typical_currency="JPY",
            typical_source_site="Google Flights",
            source_site="Google Flights",
            search_url="https://www.google.com/travel/flights/search?tfs=icn",
            stops_text="直行",
            is_lcc=True,
            checked_baggage="受託手荷物：含まれず（1個目から別料金）",
            seats_remaining="残り3席",
        )
        d2 = FlightObservation(
            route_code="NRT-HNL",
            origin="NRT",
            dest="HNL",
            city_ja="ホノルル",
            verified_origin="NRT",
            verified_dest="HNL",
            dep_date="2027-03-04",
            ret_date="2027-03-10",
            airline="ZIPAIR",
            lowest_price=58000,
            currency="JPY",
            tax_status="税込",
            typical_low=110000,
            typical_high=130000,
            typical_currency="JPY",
            typical_source_site="Google Flights",
            source_site="Google Flights",
            search_url="https://www.google.com/travel/flights/search?tfs=hnl",
            stops_text="直行",
            is_lcc=True,
            checked_baggage="受託手荷物：含まれず（1個目から別料金）",
        )
        fail = FetchFailure(
            source_site="Skyscanner",
            route_code="NRT-ICN",
            category="bot_block",
            reason_ja="ボット検知（PerimeterX）によりブロック",
        )
        md = render_report(
            [d1, d2],
            [fail],
            executed_at=datetime(2026, 11, 25, 19, 0, 0, tzinfo=JST),
        )
        self.assertIn("■ 実行サマリー", md)
        self.assertIn("確認できた路線数：2 ／ 15", md)
        self.assertIn("40%以上オフのディール件数：2件", md)
        self.assertLess(
            md.index("NRT→ICN（ソウル仁川） — 52.0%オフ"),
            md.index("NRT→HNL（ホノルル） — 51.7%オフ"),
        )
        self.assertIn(format_date_ja("2027-02-10"), md)
        self.assertIn("■ 参考観測（40%未満でも、各路線の最安は1件ずつ）", md)
        self.assertIn("■ 取得できなかったもの", md)


if __name__ == "__main__":
    unittest.main()
