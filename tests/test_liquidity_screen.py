"""Causal, fail-closed liquidity gates; all observations here are test fixtures."""
import copy
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from intraday.calendar import session
from validation import equity_sessions
from liquidity_screen import evaluate, import_verified

SCRATCH = Path(__file__).resolve().parent.parent / "work" / "liquidity_tests"
SCRATCH.mkdir(parents=True, exist_ok=True)
POLICY = {"min_share_volume": 1_000_000, "max_share_spread_bps": 10,
          "min_options_volume": 10_000, "max_options_spread_bps": 100}


def fixtures(target="2026-10-09", count=20, options=True):
    dates = equity_sessions("2026-07-01", target)[:-1][-count:]
    rows = []
    for day in dates:
        label = day.strftime("%Y-%m-%d")
        close = datetime.fromisoformat(session(label)["close"])
        rows.append({"symbol": "SPY", "session_date": label, "complete_session": True,
                     "source": "Verified session fixture", "source_timestamp": (close + timedelta(minutes=5)).isoformat(),
                     "available_at": (close + timedelta(minutes=10)).isoformat(),
                     "share_volume": 1_000_000, "share_median_spread_bps": 10,
                     "options_volume": 10_000 if options else None,
                     "options_median_spread_bps": 100 if options else None,
                     "spread_basis": "midpoint", "metric_method": "Fixture regular-session valid quote-time medians and coverage",
                     "options_scope": {"dte": [1, 3], "rights": ["C", "P"]} if options else None,
                     "method": "Fixture NBBO session median", "contract_scope": {"dte": [1, 3]},
                     "options_spread_basis": "10000 * (ask-bid) / option midpoint"})
    return rows


class LiquidityScreenTests(unittest.TestCase):
    def root(self):
        directory = tempfile.TemporaryDirectory(dir=SCRATCH)
        self.addCleanup(directory.cleanup)
        return Path(directory.name)

    def screen(self, root, dates=None, execution="options", as_of="2026-10-10T18:00:00+00:00"):
        return evaluate(root, "SPY", dates or ["2026-10-09"], POLICY, as_of, execution)

    def test_absent_history_is_unavailable_without_creating_a_data_directory(self):
        root = self.root()
        result = self.screen(root)
        self.assertEqual(result["status"], "unavailable")
        self.assertFalse(result["research_eligible"])
        self.assertEqual(result["eligible_fraction"], 0)
        self.assertFalse((root / "data").exists())

    def test_share_and_options_tracks_are_distinct_and_provenance_survives(self):
        root = self.root()
        import_verified(root, fixtures(options=False))
        shares = self.screen(root, execution="shares")
        self.assertTrue(shares["research_eligible"])
        self.assertTrue(shares["share_eligible"])
        self.assertFalse(shares["options_eligible"])
        self.assertFalse(self.screen(root)["research_eligible"])
        item = shares["session_results"][0]
        self.assertEqual(item["metrics"]["share_volume"], 1_000_000)
        self.assertEqual(item["input_sessions"][0]["contract_scope"], {"dte": [1, 3]})
        self.assertIn("option midpoint", item["input_sessions"][0]["options_spread_basis"])
        self.assertEqual(shares["spread_aggregation"], "median_of_session_medians")
        self.assertFalse(shares["execution_qualified"])

    def test_twenty_immediately_preceding_exchange_sessions_are_required(self):
        root = self.root()
        rows = fixtures(count=21)
        rows[0]["share_volume"] = 0  # the 21st-oldest session must not enter the mean
        import_verified(root, rows)
        result = self.screen(root)
        self.assertTrue(result["research_eligible"])
        self.assertEqual(len(result["session_results"][0]["input_sessions"]), 20)
        missing = self.root()
        import_verified(missing, rows[:-1])  # twenty rows exist, but the latest required one is absent
        self.assertFalse(self.screen(missing)["research_eligible"])
        partial = self.root()
        rows[-1]["complete_session"] = False
        import_verified(partial, rows)
        self.assertFalse(self.screen(partial)["research_eligible"])
        holiday = self.root()
        import_verified(holiday, fixtures(target="2026-09-08"))
        check = self.screen(holiday, ["2026-09-08"])
        self.assertTrue(check["research_eligible"])
        self.assertEqual(check["session_results"][0]["input_sessions"][-1]["session_date"], "2026-09-04")

    def test_volume_minima_and_spread_maxima_have_the_correct_inclusive_direction(self):
        for field, value, eligible in ((None, None, True), ("options_median_spread_bps", 101, False),
                                       ("options_volume", 9999, False), ("share_median_spread_bps", 11, False),
                                       ("share_volume", 999999, False)):
            with self.subTest(field=field):
                root, rows = self.root(), fixtures()
                if field:
                    for row in rows:
                        row[field] = value
                import_verified(root, rows)
                self.assertEqual(self.screen(root)["research_eligible"], eligible)

    def test_spread_basis_method_and_options_scope_are_required_and_preserved(self):
        for field, value in (("spread_basis", "dollars"), ("spread_basis", None),
                             ("metric_method", ""), ("options_scope", None), ("options_scope", {})):
            with self.subTest(field=field, value=value):
                root, rows = self.root(), fixtures()
                rows[-1][field] = value
                with self.assertRaises(ValueError):
                    import_verified(root, rows)
                self.assertFalse((root / "data").exists())
        root = self.root()
        import_verified(root, fixtures())
        observed = self.screen(root)["session_results"][0]["input_sessions"][0]
        self.assertEqual(observed["spread_basis"], "midpoint")
        self.assertIn("quote-time", observed["metric_method"])
        self.assertEqual(observed["options_scope"]["rights"], ["C", "P"])

    def test_future_or_late_metrics_never_qualify_or_leak_into_a_replay_payload(self):
        root, rows = self.root(), fixtures()
        rows[-1]["available_at"] = "2026-10-09T14:00:00+00:00"  # after the 13:30 UTC decision open
        rows[-1]["share_volume"] = 987654321
        import_verified(root, rows)
        result = self.screen(root)
        self.assertFalse(result["research_eligible"])
        self.assertIsNone(result["session_results"][0]["input_sessions"][-1])
        self.assertNotIn("987654321", json.dumps(result))
        early = self.screen(root, as_of="2026-10-09T13:00:00+00:00")
        self.assertFalse(early["research_eligible"])
        self.assertNotIn("987654321", json.dumps(early))

    def test_eighty_percent_is_evaluated_on_the_supplied_window_with_individual_failures(self):
        root, rows = self.root(), fixtures(count=24)
        rows[-1]["available_at"] = "2026-10-09T14:00:00+00:00"
        import_verified(root, rows)
        dates = ["2026-10-05", "2026-10-06", "2026-10-07", "2026-10-08", "2026-10-09"]
        result = self.screen(root, dates)
        self.assertTrue(result["research_eligible"])
        self.assertEqual(result["eligible_fraction"], .8)
        self.assertFalse(result["session_results"][-1]["research_eligible"])
        self.assertFalse(self.screen(root, dates[1:])["research_eligible"])

    def test_duplicate_conflict_corruption_and_readonly_preserve_the_journal(self):
        root, rows = self.root(), fixtures()
        self.assertEqual(import_verified(root, rows)["accepted"], 20)
        self.assertEqual(import_verified(root, rows)["duplicates"], 20)
        path = root / "data/liquidity/v1/sessions.jsonl"
        before = path.read_bytes()
        bad = copy.deepcopy(rows[0]);bad["share_volume"] += 1
        with self.assertRaises(ValueError):
            import_verified(root, [bad])
        self.assertEqual(path.read_bytes(), before)
        with patch.dict(os.environ, {"APP_REPLAY": "1"}):
            with self.assertRaises(PermissionError):
                import_verified(root, rows)
        self.assertEqual(path.read_bytes(), before)
        events = [json.loads(line) for line in before.decode().splitlines()]
        events[0]["record"]["share_volume"] += 1
        path.write_text("\n".join(json.dumps(event) for event in events) + "\n", encoding="utf-8")
        result = self.screen(root)
        self.assertEqual(result["status"], "data_blocked")
        self.assertFalse(result["research_eligible"])
        self.assertIn("hash chain", " ".join(result["reasons"]))

    def test_bad_metrics_timestamps_calendar_and_missing_policy_fail_closed(self):
        for field, value in (("share_volume", float("nan")), ("options_median_spread_bps", float("inf")),
                             ("share_volume", -1), ("share_volume", True), ("options_volume", 1.5),
                             ("complete_session", "true"), ("symbol", None), ("source", ""),
                             ("source_timestamp", "2026-10-08T12:00:00Z"),
                             ("available_at", "2026-01-01T12:00:00Z"), ("session_date", "2024-10-08")):
            with self.subTest(field=field, value=value):
                root, rows = self.root(), fixtures()
                rows[-1][field] = value
                with self.assertRaises(ValueError):
                    import_verified(root, rows)
                self.assertFalse((root / "data").exists())
        for policy in ({}, {**POLICY, "max_share_spread_bps": float("nan")}, None):
            with self.assertRaises(ValueError):
                evaluate(self.root(), "SPY", ["2026-10-09"], policy, "2026-10-10T18:00:00Z")
        self.assertFalse(self.screen(self.root(), ["2026-10-10"])["research_eligible"])


if __name__ == "__main__":
    unittest.main()
