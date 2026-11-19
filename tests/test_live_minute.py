"""Live minute bars (review A1, 2026-11-18): receipt-timed Yahoo polls, per-day live journals merged into
load_bars, labels by first-receipt delay, revisions kept, and forward eligibility scoped to the session's bars."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import live_minute  # noqa: E402
from intraday import features, store  # noqa: E402
from thesis import ops  # noqa: E402

NY = "America/New_York"
DAY = "2026-11-17"
OPEN = pd.Timestamp(f"{DAY} 09:30", tz=NY).tz_convert("UTC")


def frame(minutes, close=100.0, volume=1000.0):
    """Yahoo-style one-minute bars starting at the open (index in ET)."""
    index = pd.DatetimeIndex([OPEN + pd.Timedelta(minutes=m) for m in range(minutes)]).tz_convert(NY)
    return pd.DataFrame({"Open": close, "High": close + 0.1, "Low": close - 0.1, "Close": close, "Volume": volume}, index=index)


class Clock:
    def __init__(self, start):
        self.t = start

    def now(self):
        return self.t

    def sleep(self, seconds):
        self.t += pd.Timedelta(seconds=seconds)


class LivePollTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def poll(self, start, stop_after, fetch):
        clock = Clock(start)
        def fetch_and_stop(symbols):
            if clock.t > stop_after:
                raise KeyboardInterrupt
            return fetch(symbols, clock.t)
        try:
            live_minute.run(self.root, now=clock.now, fetch=fetch_and_stop, sleep=clock.sleep, say=lambda m: None,
                            symbols=["SPY"], busy=lambda: False)
        except KeyboardInterrupt:
            pass

    def test_bars_received_promptly_are_live_and_late_ones_are_archive(self):
        def fetch(symbols, now):  # Yahoo serves every bar that has started; the last one is still open
            minutes = int((now - OPEN).total_seconds() // 60) + 1
            return {"SPY": frame(minutes)}
        # Started at 9:40 ET: bars 9:30-9:37 were first received more than 120 seconds after closing.
        self.poll(OPEN + pd.Timedelta(minutes=10), OPEN + pd.Timedelta(minutes=14), fetch)
        events = store.read_events(store.live_folder(self.root) / f"{DAY}.jsonl")
        first = {}
        for e in events:
            first.setdefault(e["bar"]["timestamp"], e["bar"])
        labels = {pd.Timestamp(t).tz_convert(NY).strftime("%H:%M"): b["availability_basis"] for t, b in first.items()}
        self.assertEqual(labels["09:30"], "retrieved_archive")
        self.assertEqual(labels["09:38"], "observed_live")  # closed 9:39:00, received 9:40:05
        self.assertEqual(labels["09:37"], "retrieved_archive")  # closed 9:38:00, first received 9:40:05
        self.assertEqual(labels["09:42"], "observed_live")  # the last poll ran at 9:43:05
        self.assertNotIn("09:43", labels)  # still open at the last poll
        bar = first[min(first)]
        self.assertEqual((bar["source"], bar["interval_seconds"]), (live_minute.SOURCE, 60))
        status = json.loads((self.root / live_minute.STATUS).read_text(encoding="utf-8"))
        self.assertEqual(status["gaps"][0][0], OPEN.isoformat())  # started after the open: shown as a gap

    def test_changed_values_are_kept_as_a_revision(self):
        calls = {"n": 0}
        def fetch(symbols, now):
            calls["n"] += 1
            minutes = int((now - OPEN).total_seconds() // 60) + 1
            return {"SPY": frame(minutes, volume=1000.0 if calls["n"] < 3 else 1500.0)}  # Yahoo revises volume
        self.poll(OPEN, OPEN + pd.Timedelta(minutes=4), fetch)
        events = store.read_events(store.live_folder(self.root) / f"{DAY}.jsonl")
        first_bar = [e["bar"] for e in events if e["bar"]["timestamp"] == OPEN.isoformat()]
        self.assertEqual([b["volume"] for b in first_bar], [1000.0, 1500.0])
        self.assertEqual({b["availability_basis"] for b in first_bar}, {"observed_live"})  # label of the first receipt
        merged = store.load_bars(self.root, "SPY")
        self.assertEqual([b["volume"] for b in merged if b["timestamp"] == OPEN.isoformat()], [1500.0])
        early = store.load_bars(self.root, "SPY", as_of=(OPEN + pd.Timedelta(seconds=70)).isoformat())
        self.assertEqual(early[0]["volume"], 1000.0)  # as known then

    def test_an_identical_archive_copy_does_not_replace_the_live_bar(self):
        live = [{"symbol": "SPY", "timestamp": OPEN.isoformat(), "available_at": (OPEN + pd.Timedelta(seconds=65)).isoformat(),
                 "interval_seconds": 60, "open": 100, "high": 100.1, "low": 99.9, "close": 100, "volume": 1000,
                 "source": live_minute.SOURCE, "availability_basis": "observed_live"}]
        store.ingest_live(self.root, live)
        archive = dict(live[0], available_at=(OPEN + pd.Timedelta(hours=7)).isoformat(), source="Yahoo Finance / yfinance",
                       availability_basis="retrieved_archive")
        store.ingest_bars(self.root, [archive])
        self.assertEqual(store.load_bars(self.root, "SPY")[0]["availability_basis"], "observed_live")
        store.ingest_bars(self.root, [dict(archive, available_at=(OPEN + pd.Timedelta(hours=8)).isoformat(), volume=1200)])
        self.assertEqual(store.load_bars(self.root, "SPY")[0]["availability_basis"], "retrieved_archive")  # a real revision

    def test_forward_eligibility_looks_at_this_sessions_regular_bars_only(self):
        old = [{"symbol": "SPY", "timestamp": (OPEN - pd.Timedelta(days=1)).isoformat(),
                "available_at": (OPEN - pd.Timedelta(hours=10)).isoformat(), "interval_seconds": 60, "open": 99, "high": 99.1,
                "low": 98.9, "close": 99, "volume": 10, "source": "Yahoo Finance / yfinance", "availability_basis": "retrieved_archive"}]
        store.ingest_bars(self.root, old)
        bars = [{"symbol": "SPY", "timestamp": (OPEN + pd.Timedelta(minutes=m)).isoformat(),
                 "available_at": (OPEN + pd.Timedelta(minutes=m, seconds=65)).isoformat(), "interval_seconds": 60,
                 "open": 100, "high": 100.1, "low": 99.9, "close": 100, "volume": 1000, "source": live_minute.SOURCE,
                 "availability_basis": "observed_live"} for m in range(20)]
        store.ingest_live(self.root, bars)
        cutoff = OPEN + pd.Timedelta(minutes=20, seconds=10)
        snap = features.snapshot(store.load_bars(self.root, "SPY", as_of=cutoff.isoformat()), cutoff.isoformat())
        self.assertEqual(snap["quality"]["availability_bases"], ["observed_live"])
        self.assertEqual(snap["quality"]["history_availability_bases"], ["observed_live", "retrieved_archive"])
        self.assertTrue(any("Yahoo's free feed" in x for x in snap["limitations"]))


class StatusRowTests(unittest.TestCase):
    def test_the_row_names_the_tickers_and_a_missed_day(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            row = ops._live_row(root, pd.Timestamp("2026-11-18 18:00", tz=NY), ["2026-11-17", "2026-11-18"])
            self.assertEqual(row["state"], "missing")
            self.assertIn("Tickers: SPY, QQQ, IWM", row["detail"])
            path = root / live_minute.STATUS
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps({"date": "2026-11-17", "polls": 390, "live_bars": {"SPY": 390}, "late_bars": {},
                                        "gaps": [], "failures": 0, "running": False}), encoding="utf-8")
            row = ops._live_row(root, pd.Timestamp("2026-11-18 18:00", tz=NY), ["2026-11-17", "2026-11-18"])
            self.assertEqual(row["state"], "late")
            self.assertIn("Did not run on 2026-11-18", row["detail"])


class BuildPauseTests(unittest.TestCase):
    def test_nothing_is_written_under_data_while_a_build_runs(self):
        """2026-11-19: the status file written during a build made every offline build refuse to publish."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            clock = Clock(OPEN + pd.Timedelta(minutes=5))
            building = {"on": True}
            def fetch(symbols):
                if clock.t > OPEN + pd.Timedelta(minutes=9):
                    raise KeyboardInterrupt
                return {"SPY": frame(int((clock.t - OPEN).total_seconds() // 60) + 1)}
            seen = []
            def busy():
                seen.append(building["on"])
                return building["on"]
            def sleep(seconds):
                clock.sleep(seconds)
                if clock.t > OPEN + pd.Timedelta(minutes=7, seconds=30):
                    status = root / live_minute.STATUS
                    if building["on"] and status.exists():
                        written = json.loads(status.read_text(encoding="utf-8"))
                        self.assertEqual(written["polls"], 0)  # only the start-up status, before any poll
                    building["on"] = False
            try:
                live_minute.run(root, now=clock.now, fetch=fetch, sleep=sleep, say=lambda m: None, symbols=["SPY"], busy=busy)
            except KeyboardInterrupt:
                pass
            self.assertTrue(seen and seen[0])  # the build was running at the first polls
            status = json.loads((root / live_minute.STATUS).read_text(encoding="utf-8"))
            self.assertGreater(status["polls"], 0)  # written once the build was over
            self.assertTrue((store.live_folder(root) / f"{DAY}.jsonl").exists())


if __name__ == "__main__":
    unittest.main()
