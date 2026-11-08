import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import pandas as pd

from intraday import store, features, backtest, paper
from intraday.calendar import session, utc

TEST_WORK = Path(__file__).resolve().parents[1] / "work"
TEST_WORK.mkdir(parents=True, exist_ok=True)


def bar(timestamp, opening=100., high=101., low=99., close=100., volume=100., available_at=None, basis="observed_live"):
    stamp = utc(timestamp)
    return {"symbol": "SPY", "timestamp": stamp.isoformat(),
            "available_at": (utc(available_at) if available_at else stamp + pd.Timedelta(minutes=1)).isoformat(),
            "interval_seconds": 60, "open": opening, "high": high, "low": low, "close": close,
            "volume": volume, "source": "isolated-test-fixture", "availability_basis": basis}


def full_day(date="2026-11-06", *, breakout=True, ambiguous=False, basis="observed_live"):
    bounds = session(date)
    rows = [bar(stamp, basis=basis) for stamp in pd.date_range(bounds["open"], bounds["close"], freq="min", inclusive="left")]
    if breakout:
        rows[15] = bar(rows[15]["timestamp"], opening=100., high=102.5, low=100., close=102., basis=basis)
        rows[16] = bar(rows[16]["timestamp"], opening=102., high=102.5, low=100., close=102., basis=basis)
        rows[17] = bar(rows[17]["timestamp"], opening=102., high=109. if ambiguous else 103., low=98. if ambiguous else 100., close=102., basis=basis)
    return rows


class IntradayStoreTests(unittest.TestCase):
    def test_schema_rejects_naive_incomplete_or_invalid_bars(self):
        good = bar("2026-11-06T14:30:00Z")
        for field, value in (("timestamp", "2026-11-06T14:30:00"), ("available_at", "2026-11-06T14:30:30Z"),
                             ("high", 90), ("volume", -1), ("close", float("nan")), ("interval_seconds", True)):
            bad = {**good, field: value}
            with self.subTest(field=field), self.assertRaises((ValueError, TypeError)):
                store.normalize(bad)

    def test_cutoff_revisions_dedup_and_tamper_detection(self):
        original = bar("2026-11-06T14:30:00Z")
        revised = {**original, "close": 100.5, "available_at": "2026-11-06T15:00:00+00:00"}
        with tempfile.TemporaryDirectory(dir=TEST_WORK) as temp:
            self.assertEqual(store.ingest_bars(temp, [original])["accepted"], 1)
            self.assertEqual(store.ingest_bars(temp, [original])["duplicates"], 1)
            self.assertEqual(store.ingest_bars(temp, [revised])["revisions"], 1)
            self.assertEqual(store.load_bars(temp, "SPY", "2026-11-06T14:40:00Z")[0]["close"], 100.)
            self.assertEqual(store.load_bars(temp, "SPY")[0]["close"], 100.5)
            path = store.folder(temp) / "bars.jsonl"
            path.write_text(path.read_text().replace('"close": 100.0', '"close": 99.0'), encoding="utf-8")
            with self.assertRaises(ValueError):
                store.load_bars(temp, "SPY")

    def test_conflicting_batch_is_atomic_and_replay_does_not_write(self):
        row = bar("2026-11-06T14:30:00Z")
        with tempfile.TemporaryDirectory(dir=TEST_WORK) as temp:
            with self.assertRaises(ValueError):
                store.ingest_bars(temp, [row, {**row, "close": 100.1}])
            self.assertFalse((store.folder(temp) / "bars.jsonl").exists())
            with patch.dict(os.environ, {"APP_REPLAY": "1"}), self.assertRaises(PermissionError):
                store.ingest_bars(temp, [row])
            self.assertFalse((store.folder(temp) / "bars.jsonl").exists())

    def test_overlap_is_rejected(self):
        first = bar("2026-11-06T14:30:00Z")
        second = {**first, "timestamp": "2026-11-06T14:30:30Z", "interval_seconds": 30}
        with self.assertRaises(ValueError):
            store.canonical([first, second])

    def test_repeated_archive_receipt_deduplicates_but_recorrection_survives(self):
        first = bar("2026-11-06T14:30:00Z", basis="retrieved_archive")
        second = {**first, "available_at": "2026-11-06T15:00:00+00:00"}
        changed = {**second, "close": 100.5, "available_at": "2026-11-06T15:01:00+00:00"}
        reverted = {**first, "available_at": "2026-11-06T15:02:00+00:00"}
        with tempfile.TemporaryDirectory(dir=TEST_WORK) as temp:
            store.ingest_bars(temp, [first])
            self.assertEqual(store.ingest_bars(temp, [second])["duplicates"], 1)
            store.ingest_bars(temp, [changed, reverted])
            self.assertEqual(store.load_bars(temp, "SPY")[0]["close"], 100.)
            self.assertEqual(store.load_bars(temp, "SPY", "2026-11-06T15:01:30Z")[0]["close"], 100.5)

    def test_verified_caches_are_immutable_and_invalidate_on_append(self):
        first = bar("2026-11-06T14:30:00Z")
        second = bar("2026-11-06T14:31:00Z")
        with tempfile.TemporaryDirectory(dir=TEST_WORK) as temp:
            store.ingest_bars(temp, [first])
            with patch.object(store, "digest", wraps=store.digest) as verified:
                initial = store.load_bars(temp, "SPY", "2026-11-07T14:00:00Z")
                calls = verified.call_count
                initial[0]["close"] = -100
                again = store.load_bars(temp, "SPY", "2026-11-07T14:00:01Z")
                self.assertEqual(again[0]["close"], 100.)
                self.assertEqual(verified.call_count, calls)
                events = store.read_events(store.folder(temp) / "bars.jsonl")
                events[0]["bar"]["close"] = -10
                self.assertEqual(store.read_events(store.folder(temp) / "bars.jsonl")[0]["bar"]["close"], 100.)
                store.ingest_bars(temp, [second])
                self.assertEqual(len(store.load_bars(temp, "SPY")), 2)
                self.assertGreater(verified.call_count, calls)

    def test_cached_latest_does_not_replace_historical_revision_view(self):
        first = bar("2026-11-06T14:30:00Z")
        revised = {**first, "close": 100.5, "available_at": "2026-11-06T15:00:00+00:00"}
        with tempfile.TemporaryDirectory(dir=TEST_WORK) as temp:
            store.ingest_bars(temp, [first, revised])
            self.assertEqual(store.load_bars(temp, "SPY")[0]["close"], 100.5)
            old = store.load_bars(temp, "SPY", "2026-11-06T14:59:00Z")
            self.assertEqual(old[0]["close"], 100.)
            old[0]["close"] = 0
            self.assertEqual(store.load_bars(temp, "SPY", "2026-11-06T14:59:00Z")[0]["close"], 100.)


class IntradayFeatureTests(unittest.TestCase):
    def test_orb_requires_completed_range_and_cutoff_excludes_future(self):
        rows = full_day()
        before = features.snapshot(rows, "2026-11-06T14:44:00Z")
        self.assertFalse(before["orb"]["complete"])
        current = features.snapshot(rows, "2026-11-06T14:46:00Z")
        self.assertEqual(current["signal"]["state"], "candidate")
        self.assertEqual(current["orb"]["high"], 101.)
        altered = copy.deepcopy(rows)
        altered[20]["high"] = 500.
        self.assertEqual(features.snapshot(altered, current["as_of"]), current)

    def test_missing_opening_bar_and_zero_volume_abstain(self):
        rows = full_day()
        missing = features.snapshot(rows[1:], "2026-11-06T14:46:00Z")
        self.assertFalse(missing["orb"]["complete"])
        self.assertEqual(missing["signal"]["state"], "abstain")
        for row in rows:
            row["volume"] = 0
        zero = features.snapshot(rows, "2026-11-06T14:46:00Z")
        self.assertIsNone(zero["vwap"][-1]["value"])
        self.assertEqual(zero["signal"]["state"], "abstain")

    def test_archive_is_never_forward_eligible_and_stale_abstains(self):
        rows = full_day(basis="retrieved_archive")
        snap = features.snapshot(rows, "2026-11-06T14:46:00Z")
        self.assertFalse(snap["quality"]["forward_eligible"])
        stale = features.snapshot(rows[:16], "2026-11-06T15:00:00Z")
        self.assertEqual(stale["signal"]["state"], "abstain")

    def test_early_close_dst_holiday_and_unknown_year(self):
        self.assertEqual(utc(session("2026-11-27")["close"]).hour, 18)
        self.assertEqual(utc(session("2026-07-02")["close"]).hour, 20)
        self.assertFalse(session("2026-07-03")["is_session"])
        self.assertEqual(utc(session("2026-06-01")["open"]).hour, 13)
        self.assertEqual(utc(session("2026-11-06")["open"]).hour, 14)
        self.assertFalse(session("2024-11-27")["calendar_verified"])

    def test_weekend_displays_saved_chart_without_trade_permission(self):
        rows = full_day(basis="retrieved_archive")
        for row in rows:
            row["available_at"] = "2026-11-07T20:00:00+00:00"
        snap = features.snapshot(rows, "2026-11-07T20:00:01Z")
        self.assertEqual(len(snap["bars"]), 390)
        self.assertEqual(snap["session"]["date"], "2026-11-06")
        self.assertEqual(snap["market_session"]["date"], "2026-11-07")
        self.assertEqual(snap["signal"]["state"], "abstain")


class IntradayBacktestTests(unittest.TestCase):
    def test_next_event_stop_first_and_cost_monotonicity(self):
        rows = full_day(ambiguous=True)
        result = backtest.run(rows)
        self.assertEqual(result["metrics"]["trades"], 1)
        trade = result["trades"][0]
        self.assertGreater(utc(trade["entry_at"]), utc(trade["signal_known_at"]))
        self.assertEqual(trade["entry_at"], "2026-11-06T14:47:00+00:00")
        self.assertTrue(trade["ambiguous_bar_stop_first"])
        self.assertEqual(trade["exit_reason"], "stop")
        cheaper = backtest.run(rows, {"half_spread_bps": 0, "slippage_bps_per_side": 0})
        self.assertLess(trade["net_return"], cheaper["trades"][0]["net_return"])
        self.assertFalse(result["metrics"]["edge_validated"])

    def test_archive_availability_requires_explicit_scenario(self):
        rows = full_day(basis="retrieved_archive")
        for row in rows:
            row["available_at"] = "2026-11-07T20:00:00+00:00"
        self.assertEqual(backtest.run(rows)["metrics"]["trades"], 0)
        assumed = backtest.run(rows, {"assume_bar_close_availability": True})
        self.assertEqual(assumed["metrics"]["trades"], 1)
        self.assertIn("ASSUMED TIMING", assumed["limitations"][0])
        self.assertFalse(assumed["study"]["forward_eligible"])

    def test_missing_flatten_is_excluded_not_scored_as_zero(self):
        rows = full_day()
        rows = [r for r in rows if r["timestamp"] != "2026-11-06T20:55:00+00:00"]
        result = backtest.run(rows)
        self.assertEqual(result["metrics"]["complete_sessions"], 0)
        self.assertEqual(result["metrics"]["excluded_sessions"], 1)
        self.assertIsNone(result["metrics"]["scenario_compounded_return"])

    def test_late_archive_cross_does_not_revive_after_newer_known_bar(self):
        rows = full_day()
        rows[15]["available_at"] = "2026-11-06T14:47:30+00:00"
        result = backtest.run(rows)
        self.assertEqual(result["metrics"]["trades"], 0)
        self.assertEqual(result["metrics"]["no_trade_sessions"], 1)

    def test_early_close_flattens_on_correct_session(self):
        result = backtest.run(full_day("2026-11-27"))
        self.assertEqual(result["trades"][0]["exit_reason"], "stop")
        rows = full_day("2026-11-27")
        for i in range(17, len(rows)):
            rows[i] = bar(rows[i]["timestamp"], opening=102., high=103., low=100., close=102.)
        trade = backtest.run(rows)["trades"][0]
        self.assertEqual(trade["exit_reason"], "scheduled_flatten")
        self.assertEqual(trade["exit_at"], "2026-11-27T17:55:00+00:00")

    def test_invalid_parameters_and_mixed_symbols_rejected(self):
        with self.assertRaises(ValueError):
            backtest.run([], {"target_r": 20})
        with self.assertRaises(ValueError):
            backtest.run([], {"latency_seconds": 0})
        with self.assertRaises(ValueError):
            backtest.run([bar("2026-11-06T14:30:00Z"), {**bar("2026-11-06T14:31:00Z"), "symbol": "QQQ"}])

    def test_short_gap_insolvency_does_not_manufacture_compounded_equity(self):
        rows = full_day(breakout=False)
        rows[15] = bar(rows[15]["timestamp"], opening=100., high=100., low=97., close=98.)
        for i in (16, 17):
            rows[i] = bar(rows[i]["timestamp"], opening=98., high=99., low=97., close=98.)
        rows[18] = bar(rows[18]["timestamp"], opening=400., high=401., low=399., close=400.)
        result = backtest.run(rows)
        self.assertLess(result["trades"][0]["net_return"], -1)
        self.assertIsNone(result["metrics"]["scenario_compounded_return"])
        self.assertEqual(result["metrics"]["compounding_status"], "insolvent_path_suppressed")

    def test_short_entry_with_nonpositive_target_abstains(self):
        rows = full_day(breakout=False)
        rows[15] = bar(rows[15]["timestamp"], opening=100., high=100., low=97., close=98.)
        rows[16] = bar(rows[16]["timestamp"], opening=98., high=99., low=97., close=98.)
        rows[17] = bar(rows[17]["timestamp"], opening=1., high=1.5, low=.5, close=1.)
        result = backtest.run(rows)
        self.assertEqual(result["metrics"]["trades"], 0)
        self.assertIn("nonpositive", result["abstentions"][0]["reason"])


class IntradayPaperTests(unittest.TestCase):
    def test_frozen_journal_replay_idempotency_and_no_backfill_evidence(self):
        snapshot = features.snapshot(full_day(), "2026-11-06T14:46:00Z")
        with tempfile.TemporaryDirectory(dir=TEST_WORK) as temp:
            replay = paper.record_decision(temp, snapshot, replay=True)
            self.assertFalse(replay["recorded"])
            self.assertFalse(store.folder(temp).exists())
            first = paper.record_decision(temp, snapshot, now="2026-11-06T14:46:01Z", entry_at="2026-11-06T14:47:00Z")
            self.assertEqual(first["state"], "recorded_before_entry")
            duplicate = paper.record_decision(temp, snapshot, now="2026-11-06T14:46:02Z")
            self.assertEqual(duplicate["state"], "duplicate")
            with self.assertRaises(ValueError):
                paper.record_decision(temp, snapshot, config={"fee_bps_per_side": 1}, now="2026-11-06T14:46:02Z")
            archive = features.snapshot(full_day(basis="retrieved_archive"), "2026-11-06T14:46:00Z")
            blocked = paper.record_decision(temp, archive, version="archive-check-v1", now="2026-11-06T14:46:01Z")
            self.assertEqual(blocked["state"], "data_blocked")
            with self.assertRaises(ValueError):
                paper.record_outcome(temp, blocked["event"]["decision_id"],
                                     {"net_return": .01, "exit_at": "2026-11-06T15:00:00Z", "fill_model": "test"}, now="2026-11-06T15:01:00Z")
            self.assertEqual(len(paper.read_log(temp)), 4)

    def test_late_decision_and_future_outcome_cannot_be_scored(self):
        snapshot = features.snapshot(full_day(), "2026-11-06T14:46:00Z")
        with tempfile.TemporaryDirectory(dir=TEST_WORK) as temp:
            late = paper.record_decision(temp, snapshot, now="2026-11-06T14:48:00Z", entry_at="2026-11-06T14:47:00Z")
            self.assertEqual(late["state"], "late_unscored")
            with self.assertRaises(ValueError):
                paper.record_outcome(temp, late["event"]["decision_id"],
                                     {"net_return": .01, "exit_at": "2026-11-06T15:00:00Z", "fill_model": "test"}, now="2026-11-06T14:50:00Z")

    def test_old_snapshot_cannot_be_retimed_into_forward_evidence(self):
        snapshot = features.snapshot(full_day(), "2026-11-06T14:46:00Z")
        with tempfile.TemporaryDirectory(dir=TEST_WORK) as temp:
            stale = paper.record_decision(temp, snapshot, now="2026-11-06T15:00:00Z", entry_at="2026-11-06T15:01:00Z")
            self.assertEqual(stale["state"], "late_unscored")
            weekend = paper.record_decision(temp, snapshot, version="weekend-v1", now="2026-11-07T15:00:00Z", entry_at="2026-11-07T15:01:00Z")
            self.assertEqual(weekend["state"], "late_unscored")


if __name__ == "__main__":
    unittest.main()
