"""Earnings calendar, large-holding movers and release values: parsing, failure retention, time cut-offs."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from thesis import earnings_calendar as ecal, movers, releases  # noqa: E402

NY = "America/New_York"


class Reply:
    def __init__(self, payload=None, text=""):
        self.payload, self.text = payload, text

    def raise_for_status(self):
        pass

    def json(self):
        return self.payload


class EarningsCalendarTests(unittest.TestCase):
    ROWS = [{"symbol": "NVDA", "name": "NVIDIA", "marketCap": "$4,005,178,900,000", "time": "time-after-hours", "epsForecast": "$2.49", "noOfEsts": "13"},
            {"symbol": "HD", "name": "Home Depot", "marketCap": "$347,455,390,000", "time": "time-pre-market", "epsForecast": "", "noOfEsts": "11"},
            {"symbol": "TINY", "name": "Small Co", "marketCap": "$900,000,000", "time": "time-not-supplied"},
            {"symbol": "NOCAP", "name": "No value", "marketCap": "N/A"}]

    def test_day_keeps_large_companies_sorted_by_size(self):
        rows = ecal.nasdaq_day("2026-11-17", get=lambda *a, **k: Reply({"data": {"rows": self.ROWS}}))
        self.assertEqual([r["symbol"] for r in rows], ["NVDA", "HD"])
        self.assertEqual((rows[0]["timing"], rows[0]["eps_forecast"], rows[0]["estimates"]), ("after close", 2.49, 13))
        self.assertEqual((rows[1]["timing"], rows[1]["eps_forecast"]), ("before open", None))

    def test_refresh_keeps_the_last_good_copy_and_build_drops_past_days(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, now = Path(tmp), pd.Timestamp("2026-11-13 18:00", tz=NY)
            good = lambda day: [{"symbol": "NVDA", "name": "NVIDIA", "market_cap": 4e12, "timing": "after close", "eps_forecast": 2.49, "estimates": 13}]  # noqa: E731
            out = ecal.refresh(root, now, day_rows=good, pause=0)
            self.assertEqual((out["days"], out["companies"], out["failed"]), (10, 10, []))

            def broken(day):
                raise OSError("blocked")
            out = ecal.refresh(root, now, day_rows=broken, pause=0)
            self.assertEqual(len(out["failed"]), 10)
            built = ecal.build(root, pd.Timestamp("2026-11-17 09:00", tz=NY))
            self.assertEqual(built["days"][0]["date"], "2026-11-17")  # Nov 13 and 16 are past
            first = built["days"][0]
            self.assertEqual((first["ok"], first["largest"], first["rows"][0]["mega"]), (False, ["NVDA"], True))
            self.assertNotIn("2026-11-26", [d["date"] for d in built["days"]])  # Thanksgiving is not a session
            self.assertEqual(ecal.build(root / "none", now)["status"], "unavailable")


class MoversTests(unittest.TestCase):
    def test_a_large_move_is_flagged_only_for_the_known_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            days = pd.bdate_range("2026-09-01", "2026-11-13")
            frame = pd.DataFrame({"NVDA": np.linspace(100, 110, len(days)), "AAPL": np.linspace(200, 201, len(days))}, index=days)
            frame.loc[days[-1], "NVDA"] = frame["NVDA"].iloc[-2] * 0.90
            self.assertEqual(movers.refresh(root, download=lambda symbols: frame)["through"], "2026-11-13")
            out = movers.build(root, pd.Timestamp("2026-11-13 18:00", tz=NY), "2026-11-13")
            self.assertEqual([(r["symbol"], round(r["move"], 2)) for r in out["flagged"]], [("NVDA", -0.10)])
            self.assertTrue(out["current"])
            before = movers.build(root, pd.Timestamp("2026-11-13 12:00", tz=NY), "2026-11-12")  # Friday's close not known yet
            self.assertEqual((before["session"], before["flagged"]), ("2026-11-12", []))
            with self.assertRaises(ValueError):
                movers.refresh(root, download=lambda symbols: frame.iloc[:5])
            self.assertEqual(movers.build(root / "none", pd.Timestamp("2026-11-13 18:00", tz=NY), None)["status"], "unavailable")


def bls_payload():
    def series(sid, values, flag=None):
        data = [{"year": "2026" if i < 10 else "2025", "period": f"M{(10 - i) if i < 10 else (22 - i):02d}", "value": str(v),
                 "footnotes": [{"code": flag}] if flag and i == 0 else [{}]} for i, v in enumerate(values)]
        return {"seriesID": sid, "data": data}
    level = [159293, 159128, 159068] + [159000 - 50 * i for i in range(11)]
    index = [337.5 - 0.8 * i for i in range(14)]
    return {"status": "REQUEST_SUCCEEDED", "Results": {"series": [
        series("CES0000000001", level, "P"), series("LNS14000000", [4.1, 4.2] + [4.1] * 12),
        series("CES0500000003", [38.0 - 0.1 * i for i in range(14)]), series("CUSR0000SA0", index), series("CUSR0000SA0L1E", index),
        series("CUUR0000SA0", index), series("CUUR0000SA0L1E", index)]}}


class ReleaseTests(unittest.TestCase):
    def test_values_are_read_and_a_failed_source_keeps_the_saved_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bls = lambda year: releases.bls_series(year, post=lambda *a, **k: Reply(bls_payload()))  # noqa: E731
            claims = lambda: [{"week": f"2026-10-{d:02d}", "value": v} for d, v in ((17, 210000.0), (24, 205000.0), (31, 191000.0))] + [{"week": "2026-11-07", "value": 200000.0}]  # noqa: E731
            self.assertEqual(releases.refresh(root, bls=bls, claims=claims), {"bls": True, "claims": True})

            def down(*a):
                raise OSError("offline")
            status = releases.refresh(root, bls=down, claims=down)
            self.assertTrue(str(status["bls"]).startswith("failed"))
            out = releases.build(root, pd.Timestamp.now(tz=NY) + pd.Timedelta(minutes=1))
            rows = {r["name"]: r for r in out["rows"]}
            self.assertEqual((rows["Nonfarm payrolls"]["value"], rows["Nonfarm payrolls"]["previous"], rows["Nonfarm payrolls"]["preliminary"]),
                             ("+165K jobs", "+60K", True))
            self.assertEqual((rows["Unemployment rate"]["value"], rows["Unemployment rate"]["previous"]), ("4.1%", "4.2%"))
            self.assertIn("in a year", rows["CPI"]["value"])
            self.assertEqual(rows["Initial jobless claims"]["value"], "200,000")
            self.assertIn("4-week average 201,500", rows["Initial jobless claims"]["previous"])
            replay = releases.build(root, pd.Timestamp("2026-01-05 12:00", tz=NY))
            self.assertEqual(replay["status"], "unavailable")  # downloaded after the replayed moment

    def test_bls_error_status_is_an_error(self):
        with self.assertRaises(ValueError):
            releases.bls_series(2026, post=lambda *a, **k: Reply({"status": "REQUEST_NOT_PROCESSED", "message": ["daily threshold reached"]}))


if __name__ == "__main__":
    unittest.main()
