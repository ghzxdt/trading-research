"""First-release values from FRED vintages, the API key handling, and hourly-bar base rates."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import intraday_hourly as ih  # noqa: E402
from thesis import alfred  # noqa: E402

NY = "America/New_York"
KEY = "a" * 32
END = "9999-12-31"
PAYEMS = [{"date": "2026-07-01", "start": "2026-08-07", "end": END, "value": 50.0},
          {"date": "2026-08-01", "start": "2026-09-05", "end": "2026-10-02", "value": 100.0},
          {"date": "2026-08-01", "start": "2026-10-03", "end": END, "value": 101.0},
          {"date": "2026-09-01", "start": "2026-10-03", "end": "2026-11-06", "value": 150.0},
          {"date": "2026-09-01", "start": "2026-11-07", "end": END, "value": 160.0}]


class AlfredTests(unittest.TestCase):
    def test_headline_as_first_announced_and_as_revised(self):
        rows = alfred.history(PAYEMS, "level_change", "2026-11-14")
        self.assertEqual([(r["month"], r["released"], r["first"], r["current"], r["revision"]) for r in rows],
                         [("2026-08", "2026-09-05", 50.0, 51.0, 1.0), ("2026-09", "2026-10-03", 49.0, 59.0, 10.0)])
        replay = alfred.history(PAYEMS, "level_change", "2026-10-10")  # before the September revision
        self.assertEqual(replay[-1]["current"], 49.0)
        pct = alfred.history(PAYEMS, "pct_change", "2026-11-14")
        self.assertAlmostEqual(pct[-1]["first"], 150 / 101 - 1)
        level = alfred.history(PAYEMS, "level", "2026-11-14")
        self.assertEqual((level[-1]["first"], level[-1]["current"]), (150.0, 160.0))

    def test_the_key_comes_from_the_file_and_never_reaches_an_error_message(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertIsNone(alfred.api_key(root))
            (root / ".secrets").mkdir()
            (root / alfred.KEY_FILE).write_text("﻿  " + KEY + "\r\n", encoding="utf-8")
            self.assertEqual(alfred.api_key(root), KEY)
            (root / alfred.KEY_FILE).write_text("not a key", encoding="utf-8")
            self.assertIsNone(alfred.api_key(root))
            self.assertEqual(alfred.refresh(root, key=None), {"status": "no_key"})
            self.assertEqual(alfred.build(root, pd.Timestamp("2026-11-14 12:00", tz=NY))["status"], "no_key")

        def leaky(url, params=None, timeout=None):
            raise OSError(f"403 for url: {url}?api_key={params['api_key']}")
        with self.assertRaises(RuntimeError) as caught:
            alfred.vintages("PAYEMS", KEY, get=leaky)
        self.assertNotIn(KEY, str(caught.exception))
        self.assertIn("***", str(caught.exception))

    def test_refresh_build_and_calendar_check(self):
        class Reply:
            def __init__(self, payload):
                self.payload = payload

            def raise_for_status(self):
                pass

            def json(self):
                return self.payload

        def get(url, params=None, timeout=None):
            if url.endswith("release/dates"):
                return Reply({"release_dates": [{"date": "2026-12-04"}, {"date": "2027-01-08"}, {"date": "2027-02-05"}]})
            return Reply({"observations": [{"date": r["date"], "realtime_start": r["start"], "realtime_end": r["end"],
                                            "value": str(r["value"])} for r in PAYEMS] + [{"date": "2026-10-01", "realtime_start": "2026-11-07", "realtime_end": END, "value": "."}]})
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data" / "events").mkdir(parents=True)
            (root / "data" / "events" / "events.csv").write_text("date,event\n2026-12-04,jobs_report\n2027-01-09,jobs_report\n", encoding="utf-8")
            status = alfred.refresh(root, key=KEY, get=get, pause=0)
            self.assertEqual(status["payrolls"], 5)
            self.assertNotIn(KEY, (root / alfred.FILE).read_text(encoding="utf-8"))
            out = alfred.build(root, pd.Timestamp("2026-11-14 12:00", tz=NY))
            pay = next(r for r in out["rows"] if r["name"] == "Nonfarm payrolls")
            self.assertEqual((pay["month"], pay["first"], pay["current"]), ("2026-09", 49.0, 59.0))
            jobs = next(s for s in out["schedule"] if s["event"] == "jobs_report")
            self.assertEqual((jobs["missing_in_app"], jobs["extra_in_app"]), (["2027-01-08", "2027-02-05"], ["2027-01-09"]))


def bars(day, opens_closes, highs=None, lows=None):
    times = pd.date_range(f"{day} 09:30", periods=len(opens_closes), freq="h", tz=NY)
    rows = []
    for i, (t, (o, c)) in enumerate(zip(times, opens_closes)):
        rows.append({"timestamp": t, "open": o, "close": c, "volume": 1000,
                     "high": (highs or {}).get(i, max(o, c)), "low": (lows or {}).get(i, min(o, c))})
    return rows


class HourlyTests(unittest.TestCase):
    def frame(self):
        flat = [(100, 100)] * 7
        rows = bars("2026-11-10", flat)
        rows += bars("2026-11-11", [(101, 101.5), (101.5, 100.5), (100.5, 99.8), (99.8, 100.2), (100.2, 100.6), (100.6, 100.4), (100.4, 100.3)])
        rows += bars("2026-11-12", [(99.0, 98.5), (98.5, 98.0), (98.0, 97.5), (97.5, 97.0)], highs={0: 99.2}, lows={2: 97.4})
        rows += bars("2026-11-13", [(97.0, 97.1), (97.1, 97.2)])  # only two bars: incomplete, excluded
        return pd.DataFrame(rows)

    def test_session_measures(self):
        days = ih.sessions(self.frame())
        self.assertEqual(list(days["session"]), ["2026-11-11", "2026-11-12"])
        up, down = days.iloc[0], days.iloc[1]
        self.assertEqual((up["bucket"], bool(up["filled"]), bool(up["first_hour_holds"])), ("Gap up more than 0.5%", True, False))
        self.assertAlmostEqual(up["gap"], 0.01)
        self.assertTrue(up["broke_low"])  # 99.8 < the first hour's low of 101
        self.assertEqual((down["bucket"], bool(down["filled"]), bool(down["first_hour_holds"])), ("Gap down more than 0.5%", False, True))
        self.assertTrue(bool(down["broke_low"]) and bool(down["closed_below"]))

    def test_cutoff_and_interval(self):
        cut = ih.sessions(self.frame(), before=pd.Timestamp("2026-11-12 09:00", tz=NY))
        self.assertEqual(list(cut["session"]), ["2026-11-11"])
        low, high = ih.wilson(0, 3)
        self.assertEqual(low, 0.0)
        self.assertLess(high, 1.0)
        self.assertIsNone(ih.wilson(0, 0))

    def test_refresh_keeps_old_bars_and_build_points_to_the_futures_bucket(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = self.frame()
            longer = pd.concat([first] * 20, ignore_index=True)  # enough rows to pass the size check
            self.assertIn("sessions", ih.refresh(root, ("SPY",), download=lambda s: longer)["SPY"])
            extra = pd.DataFrame(bars("2026-11-16", [(97, 97.5)] * 7) * 10)
            ih.refresh(root, ("SPY",), download=lambda s: extra)
            saved = ih.load(root, "SPY")
            self.assertEqual(saved["timestamp"].dt.strftime("%Y-%m-%d").nunique(), 5)
            self.assertTrue(ih.refresh(root, ("SPY",), download=lambda s: first.iloc[:3])["SPY"].startswith("failed"))
            self.assertEqual(len(ih.load(root, "SPY")), len(saved))
            out = ih.build(root, pd.Timestamp("2026-11-17 08:00", tz=NY), [{"symbol": "ES=F", "change_since_4pm": 0.004}])
            spy = out["symbols"][0]
            self.assertEqual((spy["sessions"], spy["futures_bucket"]), (3, "Gap up 0.2% to 0.5%"))
            self.assertEqual(len(spy["rows"]), 5)


if __name__ == "__main__":
    unittest.main()
