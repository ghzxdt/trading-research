"""Review A4 (2026-11-18): a replay at moment T shows only what was published by T."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from thesis import alfred, data, earnings, earnings_calendar, risk  # noqa: E402

NY = "America/New_York"


class ReplayTimingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_a_vintage_dated_today_exists_from_8_30_am(self):
        self.assertEqual(alfred.known_day(pd.Timestamp("2026-11-06 08:00", tz=NY)), "2026-11-05")
        self.assertEqual(alfred.known_day(pd.Timestamp("2026-11-06 08:30", tz=NY)), "2026-11-06")

    def test_weekly_fred_series_are_held_back_in_a_replay_only(self):
        path = self.root / "nfci.csv"
        days = pd.date_range("2026-09-04", "2026-11-13", freq="7D")  # Fridays
        path.write_text("observation_date,NFCI\n" + "".join(f"{d:%Y-%m-%d},{i / 100}\n" for i, d in enumerate(days)),
                        encoding="utf-8")
        monday = pd.Timestamp("2026-11-16 18:00", tz=NY)
        with patch.dict(os.environ, {"APP_REPLAY": "0"}):
            self.assertEqual(data.fred(path, monday).index[-1], pd.Timestamp("2026-11-13"))
        with patch.dict(os.environ, {"APP_REPLAY": "1"}):
            # Friday Nov 13's value publishes the next Wednesday; held back 9.1 days, so the replay shows Nov 6.
            self.assertEqual(data.fred(path, monday).index[-1], pd.Timestamp("2026-11-06"))
        daily = self.root / "dgs10.csv"
        dates = pd.bdate_range("2026-11-02", "2026-11-16")
        daily.write_text("observation_date,DGS10\n" + "".join(f"{d:%Y-%m-%d},4.1\n" for d in dates), encoding="utf-8")
        with patch.dict(os.environ, {"APP_REPLAY": "1"}):
            self.assertEqual(data.fred(daily, monday).index[-1], pd.Timestamp("2026-11-13"))  # daily: unchanged rule

    def test_earnings_downloaded_after_the_moment_are_not_used(self):
        for module, payload in ((earnings, {"fetched_utc": "2026-11-18T03:00:00+00:00", "companies": {}}),
                                (earnings_calendar, {"fetched_utc": "2026-11-18T03:00:00+00:00", "days": {}})):
            path = self.root / module.FILE
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload), encoding="utf-8")
            args = (self.root, pd.Timestamp("2026-11-17 09:00", tz=NY)) + (({},) if module is earnings else ())
            with patch.dict(os.environ, {"APP_REPLAY": "1"}):
                out = module.build(*args)
            self.assertEqual(out["status"], "unavailable", module.__name__)
            self.assertIn("after this view's moment", out["reason"])

    def test_spreads_as_of_the_moment(self):
        folder = self.root / "data" / "liquidity" / "samples"
        folder.mkdir(parents=True)
        rows = [{"symbol": "SPY", "share_spread_bps": 1.0, "sampled_at": "2026-11-17T15:30:00+00:00"},
                {"symbol": "SPY", "share_spread_bps": 9.0, "sampled_at": "2026-11-17T19:30:00+00:00"}]
        (folder / "2026-11-17.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
        self.assertEqual(risk.latest_spreads(self.root, {"SPY"})["SPY"]["spread_bps"], 9.0)
        early = risk.latest_spreads(self.root, {"SPY"}, pd.Timestamp("2026-11-17 12:00", tz=NY))
        self.assertEqual(early["SPY"]["spread_bps"], 1.0)


if __name__ == "__main__":
    unittest.main()
