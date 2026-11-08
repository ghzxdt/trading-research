import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

from build_pipeline import publish_bundle, recover_publish
from stage1.sources import _fetch_etf_file, _replace_cache
from validation import ValidationError, equity_sessions, expected_session, freshness, validate_etf_cache, validate_series, write_component_manifest

TEST_WORK = Path(__file__).resolve().parents[3] / "work" / "validation_tests"
TEST_WORK.mkdir(parents=True, exist_ok=True)


def temporary_directory():
    return tempfile.TemporaryDirectory(dir=TEST_WORK)


def prices():
    return pd.DataFrame([{"date": d, "ticker": tk, "open": 100., "high": 102., "low": 99., "close": 101., "volume": 1000}
                         for d in pd.to_datetime(["2026-01-05", "2026-01-06", "2026-01-07"]) for tk in ("SPY", "QQQ")])


class InputValidationTests(unittest.TestCase):
    def test_partial_download_and_calendar_gaps_are_rejected(self):
        p = prices()
        validate_etf_cache(p, ["SPY", "QQQ"])
        for bad in (p[p.ticker == "SPY"], p.drop(index=3), pd.concat([p, p.iloc[:1]])):
            with self.assertRaises(ValidationError):
                validate_etf_cache(bad, ["SPY", "QQQ"])

    def test_bad_ohlc_and_lost_history_are_rejected(self):
        p = prices()
        bad = p.copy()
        bad.loc[0, "low"] = 103.
        with self.assertRaises(ValidationError):
            validate_etf_cache(bad, ["SPY", "QQQ"])
        with self.assertRaises(ValidationError):
            validate_etf_cache(p.iloc[2:], ["SPY", "QQQ"], p)

    def test_malformed_series_is_rejected(self):
        with self.assertRaises(ValidationError):
            validate_series(pd.DataFrame({"date": ["2026-01-05"], "v": ["HTML error"]}), "date", "v")

    def test_series_cannot_erase_valid_history_with_missing_values(self):
        previous = pd.DataFrame({"date": pd.date_range("2026-01-01", periods=5), "v": [1., 2., 3., 4., 5.]})
        candidate = previous.copy()
        candidate.loc[2, "v"] = float("nan")
        with self.assertRaises(ValidationError):
            validate_series(candidate, "date", "v", previous, allow_missing=True)

    def test_rejected_candidate_keeps_cache_byte_for_byte(self):
        p = prices()
        with temporary_directory() as folder:
            path = Path(folder) / "prices.csv"
            path.write_text(p.to_csv(index=False), encoding="utf-8")
            before = path.read_bytes()
            with mock.patch("yfinance.download", return_value=pd.DataFrame({"x": [1]})), \
                 mock.patch("stage1.sources._normalise_etfs", return_value=p[p.ticker == "SPY"]), \
                 mock.patch("stage1.sources.time.sleep"):
                status = {}
                result = _fetch_etf_file(path, ["SPY", "QQQ"], "2026-01-01", False, status)
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(set(result), {"SPY", "QQQ"})
            self.assertEqual(status["ETF prices (Yahoo)"]["how"], "failed")

    def test_cache_replacement_keeps_previous_good_bytes(self):
        with temporary_directory() as folder:
            path = Path(folder) / "data.csv"
            path.write_bytes(b"old\n")
            _replace_cache(path, "new\n")
            self.assertEqual(path.read_bytes(), b"new\n")
            self.assertEqual(path.with_name("data_previous.csv").read_bytes(), b"old\n")


class ClockTests(unittest.TestCase):
    def test_holidays_and_exceptional_closures(self):
        self.assertEqual(len(equity_sessions("2026-04-03", "2026-04-03")), 0)  # Good Friday
        self.assertEqual(len(equity_sessions("2025-01-09", "2025-01-09")), 0)  # Carter funeral
        self.assertEqual(len(equity_sessions("2021-12-31", "2021-12-31")), 1)  # Saturday New Year
        self.assertEqual(len(equity_sessions("2022-06-20", "2022-06-20")), 0)

    def test_close_publication_cutoff_and_weekend(self):
        self.assertEqual(str(expected_session("2026-11-06T16:29:00-05:00").date()), "2026-11-05")
        self.assertEqual(str(expected_session("2026-11-06T16:30:00-05:00").date()), "2026-11-06")
        self.assertEqual(str(expected_session("2026-11-08T12:00:00-05:00").date()), "2026-11-06")

    def test_stale_and_future_inputs_cannot_be_current(self):
        self.assertFalse(freshness("2026-11-04", now="2026-11-06T12:00:00-05:00")["ok"])
        self.assertFalse(freshness("2026-11-09", now="2026-11-06T12:00:00-05:00")["ok"])
        self.assertFalse(freshness("2026-11-05T00:00:00Z", kind="snapshot", now="2026-11-06T12:00:00-05:00")["ok"])

    def test_fixed_clock_manifests_are_reproducible(self):
        with temporary_directory() as folder, mock.patch.dict(os.environ, {"APP_AS_OF": "2026-11-06T12:00:00-05:00", "APP_BUILD_TIME": "fixed", "APP_RUN_ID": "test"}):
            out = Path(folder)
            write_component_manifest("test", out, {"n": 1})
            first = (out / "manifest_test.json").read_bytes()
            write_component_manifest("test", out, {"n": 1})
            self.assertEqual(first, (out / "manifest_test.json").read_bytes())


class PublicationTests(unittest.TestCase):
    def test_failed_publish_restores_previous_complete_bundle(self):
        with temporary_directory() as folder:
            parent = Path(folder)
            target, stage = parent / "output", parent / ".output-stage-test"
            target.mkdir()
            stage.mkdir()
            (target / "complete.txt").write_text("old", encoding="utf-8")
            original_rename = Path.rename

            def rename(path, destination):
                if path == stage:
                    raise PermissionError("simulated reader lock")
                return original_rename(path, destination)

            with mock.patch.object(Path, "rename", new=rename), self.assertRaises(PermissionError):
                publish_bundle(stage, target)
            self.assertEqual((target / "complete.txt").read_text(encoding="utf-8"), "old")

    def test_interrupted_publish_recovers_previous_bundle(self):
        with temporary_directory() as folder:
            parent = Path(folder)
            target, old = parent / "output", parent / ".output-previous-test"
            old.mkdir()
            (old / "complete.txt").write_text("old", encoding="utf-8")
            (parent / ".output-publish.json").write_text(json.dumps({"old": str(old)}), encoding="utf-8")
            recover_publish(target)
            self.assertEqual((target / "complete.txt").read_text(encoding="utf-8"), "old")

    def test_recovery_refuses_paths_outside_workspace(self):
        with temporary_directory() as folder:
            parent = Path(folder)
            (parent / ".output-publish.json").write_text(json.dumps({"old": str(parent.parent / "elsewhere")}), encoding="utf-8")
            with self.assertRaises(ValidationError):
                recover_publish(parent / "output")


if __name__ == "__main__":
    unittest.main()
