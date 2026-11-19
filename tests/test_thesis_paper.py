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


class VerdictV2Tests(unittest.TestCase):
    """The backtester's export moved to Lead v2 on 2026-11-14 and keeps the v1 verdict per row."""
    ROW = {"exit": "close_above_sma5", "mode": "etf_next_open", "verdict": "No edge", "verdict_v1": "Lead",
           "development": {"mean_net": 0.004, "win_rate": 0.7, "trades": 98}}

    def test_a_v1_record_keeps_its_paper_trade_when_the_verdict_changes(self):
        f = frame([100 - i for i in range(12)])
        sig = [{"symbol": "SPY", "signal": "bollinger_lower_close", "evidence": [self.ROW]}]
        v1 = {"latest_close": f"{DAYS[5]:%Y-%m-%d}", "instrument": "SPY", "direction": "long", "rules": ["bollinger_lower_close"]}
        rows = paper_book.trades([v1], {"SPY": f}, sig)
        self.assertEqual([(r["exit"], r["logged_under"], r["current_verdict"]) for r in rows], [("close_above_sma5", "v1", "No edge")])
        v2 = {**v1, "stance_rules": 2}  # a v2 record with no stored exits follows the current verdict: nothing
        self.assertEqual(paper_book.trades([v2], {"SPY": f}, sig), [])
        stored = {**v2, "rule_exits": {"bollinger_lower_close": ["close_above_sma5"]}}
        self.assertEqual(len(paper_book.trades([stored], {"SPY": f}, sig)), 1)

    def test_the_page_shows_v2_statistics_and_the_scaled_benchmark(self):
        from thesis import build
        period = {"trades": 104, "win_rate": 0.74, "mean_net": 0.0079, "random_percentile": 99,
                  "v2": {"mean_excess": 0.006, "p": 0.011, "quarters": 49},
                  "strategy": {"return_per_drawdown": 0.27}, "matched": {"return_per_drawdown": 0.49},
                  "risk_matched": {"return_per_drawdown": 0.49}}
        lead = {"exit": "close_above_sma5", "mode": "etf_next_open", "verdict": "Lead", "verdict_v1": "Lead", "q": 0.032,
                "exit_label": "x", "mode_label": "Buy at the next open", "development": period, "holdout": period}
        sig = [{"symbol": "QQQ", "signal": "bollinger_lower_close", "label": "Close below band", "fired": True,
                "close": 100.0, "trigger_close": 98.0, "sma5": 101.0, "evidence": [lead]}]
        out = build.stance(sig, {"events": {"upcoming": []}, "volatility": {}}, {}, "2026-11-13", {"usable": True})
        basis = out["basis"][0]
        self.assertEqual((basis["dev_p"], basis["q"], basis["dev_quarters"], basis["benchmark"]), (0.011, 0.032, 49, "risk_matched"))
        self.assertIn("scaled to the same time in the market and the same volatility", out["cautions"][0])


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
        self.assertEqual((row["schema"], row["close_et"]), (2, "16:00"))
        self.assertIsNone(row["quotes"]["SPY"]["age_seconds"])  # this quote had no time
        self.assertIn("usable", row["evidence_check"])  # the same check as the page and the stance log

    def test_early_close_window_and_quote_age(self):
        self.assertEqual(preclose.window("2026-11-27"), (12 * 60 + 30, 13 * 60))  # day after Thanksgiving: 1 PM close
        self.assertEqual(preclose.window("2026-11-13"), (15 * 60 + 30, 16 * 60))
        self.assertIsNone(preclose.window("2026-11-26"))  # Thanksgiving
        stamp = pd.Timestamp("2026-11-13 15:48", tz=NY).tz_convert("UTC").timestamp()
        quote = lambda s: {"price": self.last[s], "time": int(stamp)}  # noqa: E731  (Yahoo's regularMarketTime)
        preclose.record(self.root, pd.Timestamp("2026-11-13 15:50", tz=NY), quote)
        row = calls.read(self.root, preclose.LOG)[0]
        self.assertEqual(row["quotes"]["QQQ"]["age_seconds"], 120)

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
                 "2026-11-13 15:50": "preclose", "2026-11-13 20:10": "bars", "2026-11-14 10:00": "bars",
                 # 2026-11-27 closes at 1 PM: the 12:30 PM ET run is the pre-close run, the 2:30 PM ET run collects bars
                 "2026-11-27 12:10": "sample", "2026-11-27 12:31": "preclose", "2026-11-27 13:00": "bars",
                 "2026-11-27 14:30": "bars"}
        for when, slot in cases.items():
            self.assertEqual(sc.slot_for(pd.Timestamp(when, tz=NY)), slot, when)

    def test_open_slot_does_nothing_and_the_close_slot_checks_first(self):
        order = []
        kw = dict(collect=lambda root, symbols, include_options: order.append("collect") or {"results": [{"symbol": "SPY", "bar_status": "collected"}]},
                  symbols=["SPY"], sleep=lambda s: None, say=lambda m: None, lock_state=lambda r: {"busy": False},
                  preclose=lambda root, when: order.append("preclose") or "recorded",
                  sample=lambda root, symbols, when: order.append("sample") or {"sampled": 1})
        with tempfile.TemporaryDirectory() as tmp:
            sc.run(Path(tmp), now=lambda: pd.Timestamp("2026-11-13 10:00", tz=NY), **kw)
            self.assertEqual(order, [])  # it took the same-day option snapshot until 2026-11-19
            sc.run(Path(tmp), now=lambda: pd.Timestamp("2026-11-13 12:30", tz=NY), **kw)
            self.assertEqual(order, ["sample"])
            order.clear()
            sc.run(Path(tmp), now=lambda: pd.Timestamp("2026-11-13 15:50", tz=NY), **kw)
            self.assertEqual(order, ["preclose", "collect", "sample"])

if __name__ == "__main__":
    unittest.main()
