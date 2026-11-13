"""Paper book, pre-close check, same-day option snapshots, headlines card and the collection slots."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import scheduled_collect as sc  # noqa: E402
import zero_dte  # noqa: E402
from thesis import calls, news, paper_book, preclose, signals  # noqa: E402

NY = "America/New_York"
DAYS = pd.bdate_range("2026-10-01", periods=30)


def frame(closes, days=None):
    days = days if days is not None else DAYS[:len(closes)]
    close = pd.Series(np.asarray(closes, float), index=days)
    return pd.DataFrame({"open": close.shift(1).fillna(close.iloc[0]) + 0.5, "high": close + 1, "low": close - 1,
                         "close": close, "volume": 1e6})


class PaperBookTests(unittest.TestCase):
    def test_hold_5_enters_next_open_and_exits_five_sessions_after_the_signal(self):
        f = frame(np.arange(100, 112))
        day = f"{DAYS[2]:%Y-%m-%d}"
        t = paper_book.simulate(f, day, "hold_5")
        self.assertEqual((t["status"], t["entry_date"], t["exit_date"], t["sessions"]),
                         ("closed", f"{DAYS[3]:%Y-%m-%d}", f"{DAYS[7]:%Y-%m-%d}", 5))
        self.assertAlmostEqual(t["entry_price"], 102.5)  # the next session's open
        self.assertAlmostEqual(t["net"], 107 / 102.5 - 1 - paper_book.COST)
        at_close = paper_book.simulate(f, day, "hold_5", entry="close")
        self.assertEqual((at_close["entry_date"], at_close["entry_price"]), (day, 102.0))

    def test_sma5_exit_first_close_above_the_average_or_ten_sessions(self):
        falling = frame([100 - i for i in range(20)])
        t = paper_book.simulate(falling, f"{DAYS[5]:%Y-%m-%d}", "close_above_sma5")
        self.assertEqual((t["status"], t["sessions"], t["exit_reason"]), ("closed", 10, "time limit"))
        bounce = frame([100, 99, 98, 97, 96, 95, 94, 93, 99, 100])
        t = paper_book.simulate(bounce, f"{DAYS[6]:%Y-%m-%d}", "close_above_sma5")
        self.assertEqual((t["status"], t["exit_date"], t["exit_reason"]), ("closed", f"{DAYS[8]:%Y-%m-%d}", "registered exit"))

    def test_open_trade_shows_its_exit_level_and_pending_waits_for_data(self):
        f = frame([100, 99, 98, 97, 96, 95, 94, 93])
        t = paper_book.simulate(f, f"{DAYS[6]:%Y-%m-%d}", "close_above_sma5")
        self.assertEqual((t["status"], t["sessions"], t["sessions_left"]), ("open", 1, 9))
        self.assertAlmostEqual(t["exit_above"], (96 + 95 + 94 + 93) / 4)
        self.assertEqual(paper_book.simulate(f, f"{DAYS[7]:%Y-%m-%d}", "hold_5")["status"], "pending")

    def test_one_position_at_a_time_and_the_ticket(self):
        f = frame([100 - i for i in range(9)])
        lead = {"exit": "close_above_sma5", "mode": "etf_next_open", "verdict": "Lead",
                "development": {"mean_net": 0.005, "win_rate": 0.7, "trades": 90}}
        sig = [{"symbol": "QQQ", "signal": "rsi2_below_10", "evidence": [lead]}]
        rec = lambda i: {"latest_close": f"{DAYS[i]:%Y-%m-%d}", "instrument": "QQQ", "direction": "long",  # noqa: E731
                         "rules": ["rsi2_below_10"]}
        rows = paper_book.trades([rec(5), rec(6), rec(8)], {"QQQ": f}, sig)
        self.assertEqual([r["status"] for r in rows], ["open", "overlap_skipped", "overlap_skipped"])
        self.assertEqual((rows[0]["backtest_mean_net"], rows[0]["exit_from_current_evidence"]), (0.005, True))
        ticket = paper_book.ticket(rows)
        self.assertEqual(len(ticket), 1)
        self.assertIn("closes above $", ticket[0]["text"])
        waiting = paper_book.trades([rec(8)], {"QQQ": f}, sig)
        self.assertEqual(paper_book.ticket(waiting)[0]["action"], "enter")
        self.assertEqual(paper_book.scoreboard(rows)["skipped"], 2)


class PreCloseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        days = pd.bdate_range("2026-01-02", "2026-11-12")
        rng = np.random.default_rng(3)
        rows = []
        for symbol in ("SPY", "QQQ", "IWM"):
            close = 100 * np.cumprod(1 + rng.normal(0.0003, 0.01, len(days)))
            for d, c in zip(days, close):
                rows.append({"date": f"{d:%Y-%m-%d}", "ticker": symbol, "open": c, "high": c * 1.01, "low": c * 0.99, "close": c, "volume": 1e6})
        (self.root / "data" / "raw").mkdir(parents=True)
        pd.DataFrame(rows).to_csv(self.root / "data" / "raw" / "etfs.csv", index=False)
        self.last = {s: float(pd.DataFrame(rows)[lambda t: t["ticker"] == s]["close"].iloc[-1]) for s in ("SPY", "QQQ", "IWM")}

    def tearDown(self):
        self.tmp.cleanup()

    def test_recorded_once_in_the_window_and_a_crash_fires_the_rules(self):
        quote = lambda s: {"price": self.last[s] * 0.9}  # noqa: E731
        early = preclose.record(self.root, pd.Timestamp("2026-11-13 12:00", tz=NY), quote)
        self.assertFalse(early["recorded"])
        got = preclose.record(self.root, pd.Timestamp("2026-11-13 15:50", tz=NY), quote)
        self.assertTrue(got["recorded"])
        self.assertIn("SPY rsi2_below_10", got["fired"])
        again = preclose.record(self.root, pd.Timestamp("2026-11-13 15:55", tz=NY), quote)
        self.assertEqual(again["skipped"], "already recorded for this session")
        self.assertEqual(calls.verify(self.root, preclose.LOG), {"ok": True, "calls": 1})
        row = calls.read(self.root, preclose.LOG)[0]
        self.assertEqual((row["session"], row["history_through"], len(row["checks"])), ("2026-11-13", "2026-11-12", 9))

    def test_stale_history_is_not_logged(self):
        quote = lambda s: {"price": self.last[s]}  # noqa: E731
        out = preclose.record(self.root, pd.Timestamp("2026-11-16 15:50", tz=NY), quote)  # Friday's close is missing
        self.assertFalse(out["recorded"])
        self.assertIn("yesterday's refresh is missing", out["skipped"])

    def test_summary_compares_with_the_real_close(self):
        from thesis import data
        quote = lambda s: {"price": self.last[s] * 0.9}  # noqa: E731
        preclose.record(self.root, pd.Timestamp("2026-11-13 15:50", tz=NY), quote)
        etfs = data.etfs(self.root, pd.Timestamp("2026-11-13 15:50", tz=NY))
        before = preclose.summary(self.root, etfs)
        self.assertEqual((before["count"], before["compared"]), (1, 0))
        self.assertIsNone(before["sessions"][0]["checks"][0]["fired_at_close"])
        day = pd.Timestamp("2026-11-13")
        for s in etfs:  # the day then closes flat instead: every rule that looked fired has flipped
            etfs[s] = pd.concat([etfs[s], etfs[s].iloc[[-1]].set_axis([day])])
        after = preclose.summary(self.root, etfs)
        self.assertEqual(after["compared"], 9)
        self.assertGreater(after["flipped"], 0)


def cboe(symbol, session, spot, strikes):
    code = pd.Timestamp(session).strftime("%y%m%d")
    options = []
    for k, (cb, ca, pb, pa) in strikes.items():
        for right, bid, ask in (("C", cb, ca), ("P", pb, pa)):
            options.append({"option": f"{symbol}{code}{right}{int(k * 1000):08d}", "bid": bid, "ask": ask, "iv": 0.2,
                            "volume": 10, "open_interest": 5, "delta": 0.5})
    options.append({"option": f"B1{symbol}{code}C{int(spot * 1000):08d}", "bid": 9, "ask": 9, "iv": 0})
    options.append({"option": f"{symbol}261231C{int(spot * 1000):08d}", "bid": 9, "ask": 10, "iv": 0})
    return {"timestamp": "2026-11-13 09:45:00", "data": {"current_price": spot, "options": options}}


class ZeroDteTests(unittest.TestCase):
    def test_parse_keeps_todays_contracts_near_the_money_and_prices_the_straddle(self):
        payload = cboe("SPY", "2026-11-13", 757.2, {757.0: (2.0, 2.1, 1.8, 1.9), 758.0: (1.5, 1.6, 2.3, 2.4), 900.0: (0.0, 0.01, 140, 145)})
        got = zero_dte.parse(payload, "SPY", "2026-11-13")
        self.assertEqual(len(got["rows"]), 4)  # two strikes, both sides; far strike, other expiry and B1 series dropped
        s = got["straddle"]
        self.assertEqual(s["strike"], 757.0)
        self.assertAlmostEqual(s["mid"], 3.9)
        self.assertAlmostEqual(s["implied_move"], 3.9 / 757.2)
        self.assertAlmostEqual(s["spread_share"], 0.2 / 3.9)
        self.assertIsNone(zero_dte.parse(payload, "SPY", "2026-11-16"))

    def test_snapshot_saves_only_in_the_session_and_summary_settles_at_the_close(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            get = lambda url: cboe("SPY", "2026-11-13", 757.0, {757.0: (2.0, 2.2, 1.8, 2.0)})  # noqa: E731
            self.assertEqual(zero_dte.snapshot(root, pd.Timestamp("2026-11-13 08:00", tz=NY), ("SPY",), get)["saved"], 0)
            self.assertEqual(zero_dte.snapshot(root, pd.Timestamp("2026-11-14 10:00", tz=NY), ("SPY",), get)["saved"], 0)
            self.assertEqual(zero_dte.snapshot(root, pd.Timestamp("2026-11-13 10:00", tz=NY), ("SPY",), get)["saved"], 1)
            self.assertEqual(zero_dte.snapshot(root, pd.Timestamp("2026-11-13 12:30", tz=NY), ("SPY",), get)["saved"], 1)
            self.assertEqual(len((root / zero_dte.FOLDER / "chains" / "2026-11-13.jsonl").read_text().splitlines()), 2)
            waiting = zero_dte.summary(root, {})
            self.assertEqual((waiting["status"], waiting["days"], waiting["rows"][0]["days_settled"]), ("ok", 1, 0))
            spy = pd.DataFrame({"close": [763.0]}, index=[pd.Timestamp("2026-11-13")])
            row = zero_dte.summary(root, {"SPY": spy})["rows"][0]
            self.assertEqual((row["days_collected"], row["days_settled"]), (1, 1))
            self.assertAlmostEqual(row["mean_realised"], 6 / 757)
            self.assertAlmostEqual(row["straddle_mean_at_mid"], 6 / 4.0 - 1)   # worth $6 at the close, cost $4.00 at mid
            self.assertAlmostEqual(row["straddle_mean_at_ask"], 6 / 4.2 - 1)   # and $4.20 at the ask
            self.assertEqual(zero_dte.summary(Path(tmp) / "none", {})["status"], "empty")


class NewsAndSlotTests(unittest.TestCase):
    def test_headlines_since_the_close_newest_first_with_late_arrivals_marked(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / news.ARCHIVE
            path.parent.mkdir(parents=True)
            rows = [{"title": "Old", "first_seen_at": "2026-11-12T19:00:00+00:00", "published_at": "2026-11-12T18:00:00+00:00"},
                    {"title": "Late one", "first_seen_at": "2026-11-13T00:39:00+00:00", "published_at": "2026-11-12T14:12:00+00:00", "publisher": "Zacks", "symbol": "QQQ"},
                    {"title": "late ONE", "first_seen_at": "2026-11-13T01:00:00+00:00"},
                    {"title": "Morning", "first_seen_at": "2026-11-13T13:00:00+00:00", "published_at": "2026-11-13T12:50:00+00:00"},
                    {"title": "Future", "first_seen_at": "2026-11-14T13:00:00+00:00"}]
            path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
            out = news.build(root, pd.Timestamp("2026-11-13 09:00", tz=NY), "2026-11-12")
            self.assertEqual([r["title"] for r in out["rows"]], ["Morning", "Late one"])
            self.assertAlmostEqual(out["rows"][1]["late_hours"], 10.45)
            self.assertIsNone(out["rows"][0]["late_hours"])
            self.assertEqual(news.build(root / "none", pd.Timestamp("2026-11-13 09:00", tz=NY), "2026-11-12")["status"], "unavailable")

    def test_stale_and_other_ticker_headlines_are_left_out(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / news.ARCHIVE
            path.parent.mkdir(parents=True)
            rows = [{"title": "Three days old", "symbol": "SPY", "first_seen_at": "2026-11-13T06:57:00+00:00", "published_at": "2026-11-10T14:20:00+00:00"},
                    {"title": "Other ticker", "symbol": "DIA", "first_seen_at": "2026-11-13T06:57:00+00:00", "published_at": "2026-11-13T06:00:00+00:00"},
                    {"title": "Fed release", "symbol": "*", "first_seen_at": "2026-11-13T06:57:00+00:00", "published_at": "2026-11-12T19:00:00+00:00"}]
            path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
            out = news.build(root, pd.Timestamp("2026-11-13 09:00", tz=NY), "2026-11-12")
            self.assertEqual([r["title"] for r in out["rows"]], ["Fed release"])

    def test_collection_slots(self):
        cases = {"2026-11-13 09:40": "bars", "2026-11-13 10:00": "open", "2026-11-13 10:30": "sample", "2026-11-13 14:30": "sample",
                 "2026-11-13 15:50": "options", "2026-11-13 20:10": "bars", "2026-11-14 10:00": "bars"}
        for when, slot in cases.items():
            self.assertEqual(sc.slot_for(pd.Timestamp(when, tz=NY)), slot, when)

    def test_open_slot_takes_the_option_snapshot_only_and_the_close_slot_checks_first(self):
        order = []
        kw = dict(collect=lambda root, symbols, include_options: order.append("collect") or {"results": [{"symbol": "SPY", "bar_status": "collected", "options_status": "indicative_only"}]},
                  symbols=["SPY"], sleep=lambda s: None, say=lambda m: None, lock_state=lambda r: {"busy": False},
                  zero=lambda root, when: order.append("zero") or "saved", preclose=lambda root, when: order.append("preclose") or "recorded",
                  sample=lambda root, symbols, when: order.append("sample") or {"sampled": 1})
        with tempfile.TemporaryDirectory() as tmp:
            sc.run(Path(tmp), now=lambda: pd.Timestamp("2026-11-13 10:00", tz=NY), **kw)
            self.assertEqual(order, ["zero"])
            order.clear()
            sc.run(Path(tmp), now=lambda: pd.Timestamp("2026-11-13 12:30", tz=NY), **kw)
            self.assertEqual(order, ["sample", "zero"])
            order.clear()
            sc.run(Path(tmp), now=lambda: pd.Timestamp("2026-11-13 15:50", tz=NY), **kw)
            self.assertEqual(order[:3], ["preclose", "zero", "collect"])


if __name__ == "__main__":
    unittest.main()
