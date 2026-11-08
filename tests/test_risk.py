"""Regression cases for risk availability, side inputs and publication-time behavior."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd

from leverage import build, kalshi
from gex import build as gex_build, data as gex_data


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEST_SCRATCH = (PROJECT_ROOT / "work" / "risk_tests").resolve()
if not TEST_SCRATCH.is_relative_to(PROJECT_ROOT):
    raise RuntimeError("Test scratch escaped the project workspace")
TEST_SCRATCH.mkdir(parents=True, exist_ok=True)


def market(**changes):
    value = {"ticker": "KXUS500PERP", "title": "US500", "status": "active", "asset_class": "Indices",
             "price": "100", "bid": "99", "ask": "101", "leverage_estimate": 10,
             "long_leverage_estimates": {"1000": 12, "10000": 8},
             "short_leverage_estimates": {"1000": 10, "10000": 7}}
    value.update(changes)
    return value


def rows_for(*markets):
    return build.market_rows({"markets": list(markets), "funding": pd.DataFrame(),
                              "risk": {"initial_margin_multiplier": {m["ticker"]: 1.3 for m in markets}}})


def bars():
    return pd.DataFrame({"spy_close": [100.] * 8, "spy_high": [101.] * 8, "spy_low": [99.] * 8},
                        index=pd.bdate_range("2026-10-05", periods=8))


def snapshots(*rows):
    return pd.DataFrame(rows, columns=["snapshot_utc", "ticker", "bid", "ask", "is_open"])


class ClosedMarketSpreadTests(unittest.TestCase):
    """A closed market's resting quotes are not a usable spread (quant review, 2026-11-07)."""

    def spread_row(self, m, **raw):
        return build.market_rows({"markets": [m], "funding": pd.DataFrame(), "risk": {}, **raw}).iloc[0]

    def test_open_market_shows_its_live_spread(self):
        r = self.spread_row(market(schedule={"is_open": True}))
        self.assertAlmostEqual(r["spread"], 2 / 100)
        self.assertEqual(r["spread_basis"], "Live")
        self.assertEqual(build.spread_text(r), "2.00% (live)")

    def test_round_the_clock_market_without_schedule_counts_as_open(self):
        self.assertEqual(self.spread_row(market())["spread_basis"], "Live")

    def test_closed_market_uses_the_latest_open_quote_with_its_time(self):
        snaps = snapshots(("2026-11-06T05:14:43Z", "KXUS500PERP", 99.9, 100.1, True),
                          ("2026-11-06T06:17:09Z", "KXUS500PERP", 99.95, 100.05, True),
                          ("2026-11-07T23:33:05Z", "KXUS500PERP", 90.0, 110.0, False))
        r = self.spread_row(market(schedule={"is_open": False}, bid="90", ask="110"), snapshots=snaps)
        self.assertAlmostEqual(r["spread"], 0.1 / 100)
        self.assertAlmostEqual(r["half_spread"], 0.05 / 100)
        self.assertEqual(r["spread_basis"], "Market closed; last open quote Fri Nov 6, 1:17 AM ET")
        self.assertEqual(build.spread_text(r), "0.10% (market closed; last open quote Fri Nov 6, 1:17 AM ET)")

    def test_newer_twice_daily_quote_wins_and_placeholder_asks_are_ignored(self):
        snaps = snapshots(("2026-11-06T06:17:09Z", "KXUS500PERP", 99.95, 100.05, True))
        quotes = snapshots(("2026-11-06T21:05:00Z", "KXUS500PERP", 99.99, 100.01, "True"),
                           ("2026-11-06T22:05:00Z", "KXUS500PERP", 99.0, 922337203685477.5807, "True"))
        r = self.spread_row(market(schedule={"is_open": False}), snapshots=snaps, perp_quotes=quotes)
        self.assertAlmostEqual(r["spread"], 0.02 / 100)
        self.assertIn("Fri Nov 6, 4:05 PM ET", r["spread_basis"])

    def test_closed_market_without_history_is_blank_not_the_closed_quote(self):
        r = self.spread_row(market(schedule={"is_open": False}, bid="90", ask="110"))
        self.assertTrue(np.isnan(r["spread"]))
        self.assertEqual(r["spread_basis"], "Market closed; no open-market quote saved yet")
        self.assertEqual(build.spread_text(r), "- (market closed; no open-market quote saved yet)")


class RiskAvailabilityTests(unittest.TestCase):
    def test_unknown_barrier_is_unavailable_not_zero_risk(self):
        for value in [np.nan, 0, -0.01, np.inf]:
            result = build._hit_rates(bars(), "SPY", value)
            self.assertFalse(result["available"])
            for key in ["long_1", "short_1", "long_5", "short_5", "long_1_recent"]:
                self.assertTrue(np.isnan(result[key]), (value, key))

    def test_valid_no_hits_is_distinct_from_unknown(self):
        result = build._hit_rates(bars(), "SPY", .05)
        self.assertTrue(result["available"])
        self.assertEqual(result["long_1"], 0.)
        self.assertEqual(result["n_1"], 7)
        self.assertEqual(result["n_5"], 3)

    def test_side_estimates_are_not_replaced_by_generic(self):
        good = rows_for(market()).iloc[0]
        self.assertEqual(good["max_leverage_long"], 12)
        self.assertEqual(good["max_leverage_short"], 10)
        self.assertLess(good["cushion_long"], good["cushion_short"])
        self.assertEqual(good["cushion_at_max"], min(good["cushion_long"], good["cushion_short"]))
        self.assertEqual(good["liquidation_model_status"], "uncalibrated_proxy")
        self.assertAlmostEqual(good["spread"], .02)
        self.assertAlmostEqual(good["half_spread"], .01)
        missing = rows_for(market(long_leverage_estimates={})).iloc[0]
        self.assertTrue(np.isnan(missing["cushion_at_max"]))
        self.assertEqual(missing["liquidation_model_status"], "missing_inputs")
        study = build.study_liquidation(pd.DataFrame([missing]), bars())
        self.assertEqual(study["tables"], [])
        self.assertIn("unavailable", study["findings"][0]["headline"])


class FundingTests(unittest.TestCase):
    def funding(self, days, rates):
        return pd.DataFrame({"market_ticker": "X", "funding_time": pd.to_datetime(days, utc=True),
                             "funding_rate": rates, "mark_price": 100.})

    def test_zero_transfer_is_not_shorts_paying(self):
        result = build.funding_stats(self.funding(["2026-10-01", "2026-10-02", "2026-10-03"], [.001, 0, -.001]), "X")
        self.assertAlmostEqual(result["longs_paid"], 1/3)
        self.assertAlmostEqual(result["shorts_paid"], 1/3)
        self.assertAlmostEqual(result["zero"], 1/3)
        self.assertEqual(result["day"], 0.)
        self.assertEqual(result["coverage"], 1.)

    def test_missing_interval_does_not_reduce_average_silently(self):
        f = self.funding(["2026-10-01", "2026-10-02", "2026-10-04", "2026-10-05"], [.001] * 4)
        result = build.funding_stats(f, "X")
        self.assertEqual(result["coverage"], .8)
        self.assertTrue(np.isnan(result["day"]))
        self.assertTrue(np.isnan(result["year"]))

    def test_one_record_cannot_establish_annualized_schedule(self):
        result = build.funding_stats(self.funding(["2026-10-01"], [.001]), "X")
        self.assertTrue(np.isnan(result["year"]))
        self.assertEqual(result["last"], .001)

    def test_tracking_excludes_return_spanning_missing_session(self):
        dates = pd.bdate_range("2026-10-05", periods=5)
        t = pd.DataFrame({"spy_close": [100, 101, 102, 103, 104]}, index=dates)
        funding = pd.DataFrame({"market_ticker": "KXUS500PERP", "funding_time": dates[[0, 2, 3, 4]].tz_localize("America/New_York") + pd.Timedelta(hours=16),
                                "mark_price": [100, 102, 103, 104]})
        study = build.study_tracking(rows_for(market()), funding, t)
        self.assertEqual(study["tables"][0]["rows"][0][2], "2")
        self.assertIn("1 nonconsecutive", study["findings"][0]["detail"])


class GexTests(unittest.TestCase):
    def frame(self):
        j = pd.DataFrame(index=pd.bdate_range("2026-11-02", periods=4))
        j["gex_known"] = -1.
        j["expected_move"] = .01
        j["vix"] = 20.
        j["spy_daytime_vs_expected"] = 1.
        for proxy, day, high, low in [("spy", .01, 101., 90.), ("qqq", .02, 110., 99.)]:
            j[proxy + "_open"] = 100.
            j[proxy + "_high"] = high
            j[proxy + "_low"] = low
            j[proxy + "_daytime"] = day
        return j

    def test_adverse_paths_and_proxy_scaling_are_separate(self):
        lev = pd.DataFrame([{"ticker": ticker, "name": name, "status": "active", "liquidation_model_status": "uncalibrated_proxy",
                             "cushion_long": .05, "cushion_short": .05, "max_leverage_long": 5, "max_leverage_short": 5}
                            for ticker, name in [("KXUS500PERP", "US500"), ("KXUSTECH100PERP", "Tech")]])
        rows = gex_build._conditional_risk_rows(self.frame(), lev, True, .01)
        self.assertEqual([r[5] for r in rows], ["5.0", "5.0", "2.5", "2.5"])
        self.assertEqual([r[7] for r in rows], ["100.0%", "0.0%", "0.0%", "100.0%"])
        # The SPY long hit comes from its low despite the positive endpoint return.
        self.assertEqual(rows[0][6], "4")

    def test_stale_current_conditionals_are_suppressed(self):
        j = self.frame()
        dix = pd.DataFrame({"gex": [-1.], "dix": [.4]}, index=j.index[-1:])
        with patch.dict(os.environ, {"APP_AS_OF": "2026-12-01T10:00:00-05:00"}):
            study = gex_build.study_reading(j, dix, rows_for(market()))
        self.assertFalse(study["current_usable"])
        self.assertEqual(study["tables"], [])
        self.assertFalse(any("current VIX" in x["label"] for x in study["tiles"]))

    def test_rank_and_known_columns_do_not_use_future_data(self):
        dates = pd.bdate_range("2024-01-02", periods=300)
        dix = pd.DataFrame({"gex": np.arange(300), "dix": np.linspace(.3, .5, 300)}, index=dates)
        full = gex_data.joined(pd.DataFrame(index=dates), dix)
        part = gex_data.joined(pd.DataFrame(index=dates[:250]), dix.iloc[:250])
        pd.testing.assert_frame_equal(part, full.iloc[:250])
        self.assertTrue(np.isnan(gex_data.dix_rank(dix.dix).iloc[198]))
        self.assertEqual(gex_data.dix_rank(dix.dix).iloc[199], 1.)


class CacheTests(unittest.TestCase):
    def test_invalid_download_preserves_bytes_and_timestamp(self):
        with tempfile.TemporaryDirectory(dir=TEST_SCRATCH) as directory:
            root = Path(directory)
            path = root / "markets.json"
            content = json.dumps({"markets": [market()]})
            path.write_text(content)
            before = path.stat().st_mtime_ns
            status = {}
            with patch.object(kalshi, "RAW", root):
                loaded = kalshi._cached("markets.json", lambda: {"markets": []}, False, status, "test")
            self.assertEqual(path.read_text(), content)
            self.assertEqual(path.stat().st_mtime_ns, before)
            self.assertEqual(loaded["markets"][0]["ticker"], "KXUS500PERP")
            self.assertEqual(status["test"]["how"], "failed")
            self.assertIsNotNone(status["test"]["saved"].tzinfo)

    def test_offline_read_never_fetches_or_rewrites_cache(self):
        with tempfile.TemporaryDirectory(dir=TEST_SCRATCH) as directory:
            root = Path(directory)
            path = root / "markets.json"
            path.write_text(json.dumps({"markets": [market()]}))
            before = path.stat().st_mtime_ns
            with patch.object(kalshi, "RAW", root):
                kalshi._cached("markets.json", lambda: self.fail("offline fetch"), True, {}, "test")
            self.assertEqual(path.stat().st_mtime_ns, before)


if __name__ == "__main__":
    unittest.main()
