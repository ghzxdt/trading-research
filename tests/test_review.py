"""The Review page: v1 (2026-11-19) and v2 (2026-11-21, the backtester chat's spec, approved by the user).

v2's fixture tests, as the spec lists them: the exit close, the holding window in exchange sessions, the tag
mapping, the one-bet grouping, the drawdown comparison group and the sizing arithmetic; plus the ATR-scaled
"near a trigger", the price levels, the open rule trades and the page's modes.
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from thesis import evidence_cards, levels, paper_book, review, signals  # noqa: E402

LEAD = {"mode": "etf_next_open", "verdict": "Lead", "exit": "close_above_sma5",
        "exit_label": "First close above the 5-day average (max 10)", "forward": {"trades": 1, "status": "too few"}}
BOLL = "Close below the lower Bollinger band (20, 2)"
RSI14 = "RSI(14) below 30"
CARD = {"exit": "close_above_sma5", "entry": "etf_next_open", "trades_per_year": 6.0, "trades": 104, "mean_net": 0.0079,
        "median_net": 0.0113, "net_p10": -0.0127, "worst_trade": -0.151, "worst_inside": -0.197,
        "trades_mae_below_5pct": 13, "excess": 0.006, "excess_ci90": [0.002, 0.009], "development": {"start": "2010-01-01"},
        "leveraged": {"instrument": "TQQQ", "trades": 102, "worst_net": -0.476, "mae_worst": -0.525}}


def state(direction="long", fired=True, rules=(BOLL,)):
    sig = [{"symbol": "QQQ", "signal": "bollinger_lower_close", "label": BOLL, "fired": fired, "near_trigger": not fired,
            "close": 640.0, "trigger_close": 645.0 if fired else 630.0, "value": 642.0, "sma5": 655.0, "exit_close": 652.5,
            "evidence": [LEAD], "cards": [CARD]},
           {"symbol": "QQQ", "signal": "rsi14_below_30", "label": RSI14, "fired": fired and RSI14 in rules, "near_trigger": False,
            "close": 640.0, "trigger_close": 641.0, "value": 28.0, "sma5": 655.0, "exit_close": 652.5,
            "evidence": [LEAD], "cards": [dict(CARD, trades=26, worst_inside=-0.116)]}]
    basis = [{"symbol": "QQQ", "rule": r, "exit": "First close above the 5-day average (max 10)", "dev_trades": 104} for r in rules]
    return {"as_of": "2026-11-20T18:00:00-05:00", "latest_close": "2026-11-20", "next_entry_et": "2026-11-23T09:30:00-05:00",
            "stance": {"direction": direction, "headline": "Long candidate" if direction == "long" else "Flat",
                       "basis": basis if direction == "long" else []},
            "signals": sig,
            "regime": {"volatility": {"vix": 26.0, "vix3m": 25.0, "level": "elevated", "term_ratio": 1.04},
                       "events": {"upcoming": [{"date": "2026-11-24", "label": "Jobs report"}]},
                       "trend": {"QQQ": {"close": 640.0, "sma50": 700.0, "sma200": 680.0},
                                 "SPY": {"close": 600.0, "vs_sma200": -0.05}}},
            "earnings": {"rows": []}, "ops": {"rows": [{"label": "Live minute bars", "state": "late", "detail": "gap"}]},
            "evidence_check": {"age_days": 3, "checked_through": "2026-11-17"},
            "paper_book": {"trades": [], "ticket": [{"action": "enter", "text": "Enter: paper long QQQ"}]},
            "calls": {"calls": [{"relation": "take", "status": "scored", "call_return": 0.02, "direction": "long",
                                 "opportunity_ids": ["a"]}]},
            "stance_log": {"missed_closes": ["2026-11-16"], "records": [
                {"latest_close": "2026-11-13", "opportunities": [{"id": "a", "disposition": "long"}, {"id": "b", "disposition": "long"}]}]},
            "ideas": {"ideas": [], "counts": {}}}


FILTERS = {"generated_at": "2026-11-18T07:08:30+00:00", "tests": [
    {"test": "vix_level", "strategy": "QQQ:bollinger_lower_close+close_above_sma5|etf_next_open", "group_label": "VIX 20 or higher",
     "group": 60, "rest": 44, "diff": 0.002, "p": 0.64, "q": 0.94, "label": "Insufficient evidence"},
    {"test": "vix_level", "strategy": "QQQ:rsi14_below_30+close_above_sma5|etf_next_open", "group_label": "VIX 20 or higher",
     "group": 23, "rest": 3, "diff": None, "p": None, "q": None, "label": "Too few trades"},
    {"test": "gap_at_next_open", "strategy": "QQQ:bollinger_lower_close+close_above_sma5|etf_next_open",
     "group_label": "gap up 0.5% or more", "group": 29, "rest": 75, "diff": -0.0127, "p": 0.03, "q": 0.108,
     "label": "Insufficient evidence", "holdout": {"status": "ok", "diff": 0.0062}},
    {"test": "volatility_matched_baseline", "strategy": "QQQ:bollinger_lower_close+close_above_sma5|etf_next_open",
     "diff": 0.005, "ci90": [0.001, 0.008], "p": 0.025, "q": 0.108, "label": "Not shown beyond volatility"}]}


def trade_list():
    rows = []
    for i, (mae, net) in enumerate([(-0.01, 0.01), (-0.08, -0.03), (-0.09, 0.02), (-0.02, 0.01), (-0.12, -0.10)]):
        rows.append({"symbol": "QQQ", "signal": "rsi2_below_10", "exit": "close_above_sma5", "pricing": "etf_close",
                     "period": "development", "signal_day": f"2020-01-{i + 10:02d}", "exit_day": f"2020-01-{i + 15:02d}",
                     "mae": mae, "net": net, "sessions": 3})
    rows.append(dict(rows[0], period="holdout", signal_day="2001-01-10", mae=-0.10, net=0.04))
    return pd.DataFrame(rows)


def exports(tmp: Path, filters=FILTERS, trades=True) -> Path:
    folder = tmp / "exports"
    (folder / "trades").mkdir(parents=True)
    (folder / "filter_tests.json").write_text(json.dumps(filters), encoding="utf-8")
    (folder / "trade_simulation.json").write_text(json.dumps({"verdict_changes": [], "trade_list": "exports/trades/run.csv"}),
                                                  encoding="utf-8")
    if trades:
        trade_list().to_csv(folder / "trades" / "run.csv", index=False)
    return folder


def frame(closes, highs=None, lows=None, start="2026-06-01"):
    index = pd.bdate_range(start, periods=len(closes))
    closes = np.asarray(closes, float)
    return pd.DataFrame({"open": closes, "high": highs if highs is not None else closes + 1,
                         "low": lows if lows is not None else closes - 1, "close": closes}, index=index)


class ReviewV1Tests(unittest.TestCase):
    def test_a_long_setup_gives_a_plan_without_assuming_a_loss_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = review.build(state(), Path(tmp), export_dir=Path(tmp) / "missing")  # no backtester files at all
        [plan] = out["today"]["plan"]
        self.assertEqual((plan["symbol"], plan["loss_at_limit"]), ("QQQ", "set a loss limit"))
        self.assertIn("5-day average", plan["rules"][0]["exit_rule"])
        self.assertIn("652.50", plan["exit_lines"][0])  # the exit close, not the 5-day average (655)
        texts = " ".join(c["text"] for c in out["headline"])
        self.assertIn("set a loss limit", texts)
        self.assertIn("weekend or holiday", texts)  # Friday close, Monday open
        self.assertIn("Jobs report", texts)
        self.assertTrue(all(c.get("source") for c in out["headline"]))
        self.assertIn("not found", " ".join(c["text"] for c in out["changes"]["callouts"]))
        self.assertEqual(out["record"]["calls_by_relation"]["take"]["scored"], 1)
        self.assertEqual(out["record"]["calls_by_relation"]["take"]["judge"], "too few to judge")
        self.assertEqual(out["queue"]["forward_checks"][0]["months_to_check"], 8)  # 4 more trades at 6 a year
        self.assertEqual(out["sources"]["trade_list"], "not found")

    def test_a_near_trigger_lead_is_a_watch_and_filter_tests_are_one_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = exports(Path(tmp))
            out = review.build(state("flat", fired=False), Path(tmp), export_dir=folder)
        watch = [c["text"] for c in out["today"]["callouts"] if c["level"] == "watch"]
        self.assertTrue(any("closes at or below $630.00" in t for t in watch))
        filters = [c for c in out["changes"]["callouts"] if "Filter tests" in c["text"]]
        self.assertEqual(len(filters), 1)
        self.assertEqual(filters[0]["level"], "info")
        self.assertEqual(len(out["changes"]["filter_tests"]["notable"]), 2)  # Too few trades, Not shown beyond volatility


class ExitAndWindowTests(unittest.TestCase):
    def test_the_exit_close_is_the_mean_of_the_last_four_closes(self):
        closes = list(np.linspace(150, 100, 60)) + [100, 104, 108, 112, 90]
        [sig] = [s for s in signals.build({"QQQ": frame(closes)})["signals"] if s["signal"] == "rsi2_below_10"]
        self.assertAlmostEqual(sig["sma5"], 102.8)
        self.assertAlmostEqual(sig["exit_close"], 103.5)  # differs from the 5-day average
        for nxt, exits in ((103.6, True), (103.4, False)):  # x exits when x > mean(last 4 closes, x)
            window = [104, 108, 112, 90, nxt]
            self.assertEqual(nxt > sum(window) / 5, exits)
        trade = paper_book.simulate(frame(closes), f"{frame(closes).index[-2]:%Y-%m-%d}", "close_above_sma5", "close")
        self.assertAlmostEqual(trade["exit_above"], sig["exit_close"])

    def test_the_holding_window_counts_exchange_sessions(self):
        self.assertEqual(review.sessions_after("2026-11-20", 5)[-1], "2026-11-30")  # Thanksgiving is not a session
        self.assertEqual(review.sessions_after("2026-11-20", 10)[-1], "2026-12-07")
        window = review.holding_window("2026-11-20", 10)
        self.assertEqual((window["from"], window["to"], window["sessions"]), ("2026-11-23", "2026-12-07", 10))
        self.assertEqual(window["closed"], ["2026-11-26"])
        self.assertEqual(window["early_closes"], ["2026-11-27"])
        found = review.catalysts({"regime": {"events": {"upcoming": [{"date": "2026-12-04", "label": "Jobs report"},
                                                                      {"date": "2026-12-10", "label": "CPI"}]}},
                                  "earnings": {"rows": [{"name": "Broadcom", "next_date": "2026-12-03"}]}},
                                 "2026-11-20", window)
        self.assertEqual([c["kind"] for c in found], ["holiday", "half day", "earnings", "release"])
        self.assertEqual(found[0]["what"], "Market closed (Thanksgiving)")

    def test_a_release_later_than_five_sessions_is_not_tagged_by_the_release_test(self):
        s = state(rules=(BOLL, RSI14))
        s["regime"]["events"]["upcoming"] = [{"date": "2026-12-04", "label": "Jobs report"}]
        with tempfile.TemporaryDirectory() as tmp:
            out = review.build(s, Path(tmp), export_dir=exports(Path(tmp)))
        [window] = [c for c in out["today"]["callouts"] if c["text"].startswith("In the holding window")]
        self.assertIn("does not apply", window["text"])
        self.assertNotIn("tags", window)


class TagTests(unittest.TestCase):
    def test_the_tag_mapping(self):
        cases = [({"label": "Too few trades", "p": None}, "untested"),
                 ({"label": "No meaningful difference", "p": 0.94, "q": 0.94, "diff": 0.001}, "no_effect"),
                 ({"label": "Insufficient evidence", "p": 0.64, "q": 0.94, "diff": 0.002}, "no_effect"),
                 ({"label": "Insufficient evidence", "p": 0.03, "q": 0.108, "diff": -0.013}, "unresolved"),
                 ({"label": "Meaningful difference", "p": 0.01, "q": 0.05, "diff": -0.013,
                   "holdout": {"status": "ok", "diff": 0.004}}, "unresolved"),  # 1993-2009 pointed the other way
                 ({"label": "Meaningful difference", "p": 0.01, "q": 0.05, "diff": -0.013,
                   "holdout": {"status": "ok", "diff": -0.004}}, "difference"),
                 (None, "untested")]
        for test, expected in cases:
            self.assertEqual(review.tag(test)["tag"], expected, test)

    def test_tags_follow_the_rule_in_play_and_are_worded_per_rule(self):
        rules = [{"symbol": "QQQ", "signal": "bollinger_lower_close", "exit": "close_above_sma5", "mode": "etf_next_open", "short": "Bollinger"},
                 {"symbol": "QQQ", "signal": "rsi14_below_30", "exit": "close_above_sma5", "mode": "etf_next_open", "short": "RSI(14)"}]
        text = review.phrase(review.tags_for("vix_level", rules, FILTERS))
        self.assertIn("tested on Bollinger, no difference shown", text.replace("tested on Bollinger and", "x"))
        self.assertIn("untested (too few trades) for RSI(14)", text)
        both = review.phrase([dict(t, rule=r) for t, r in zip(review.tags_for("vix_level", rules[:1], FILTERS) * 2, ("A", "B"))])
        self.assertEqual(both, "tested on both rules, no difference shown")
        gap = review.phrase(review.tags_for("gap_at_next_open", rules[:1], FILTERS))
        self.assertIn("unresolved", gap)
        self.assertIn("1.3% worse", gap)
        self.assertIn("1993-2009 did not show it", gap)
        self.assertEqual(review.tags_for("vix_level", [dict(rules[0], exit="hold_5")], FILTERS)[0]["tag"], "untested")

    def test_the_vix_callout_is_about_size_and_tagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = review.build(state(rules=(BOLL, RSI14)), Path(tmp), export_dir=exports(Path(tmp)))
        [vix] = [c for c in out["today"]["callouts"] if c["text"].startswith("VIX")]
        self.assertIn("matters for size", vix["text"])
        self.assertNotIn("stress reading", vix["text"])
        self.assertEqual({t["tag"] for t in vix["tags"]}, {"no_effect", "untested"})
        gap = [c for c in out["today"]["callouts"] if c["text"].startswith("If the next open")]
        self.assertEqual(len(gap), 1)


class TradeTests(unittest.TestCase):
    def test_several_leads_on_one_close_are_one_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = review.build(state(rules=(BOLL, RSI14)), Path(tmp), export_dir=exports(Path(tmp)))
        [plan] = out["today"]["plan"]
        self.assertTrue(plan["one_bet"])
        self.assertEqual([r["short"] for r in plan["rules"]], ["Bollinger", "RSI(14)"])
        self.assertEqual(len(plan["exit_lines"]), 1)  # the same exit is shown once
        self.assertEqual(plan["time_stop"], "2026-12-07")
        acts = [c for c in out["today"]["callouts"] if c["level"] == "act"]
        self.assertEqual(len(acts), 1)
        self.assertIn("one bet, one size", acts[0]["text"])
        self.assertIn("13 went more than 5% against", acts[0]["text"])
        self.assertIn("TQQQ version: worst -47.6%", acts[0]["text"])
        self.assertEqual(plan["rules"][0]["spread"]["median_net"], 0.0113)
        self.assertTrue(plan["rules"][1]["spread"]["small"])  # 26 trades

    def test_the_drawdown_comparison_group(self):
        group = review.drawdown_group(trade_list(), "QQQ", "rsi2_below_10", "close_above_sma5", "etf_close", -0.077)
        self.assertEqual(group["development"], {"trades": 5, "reached": 3, "finished_positive": 1})
        self.assertEqual(group["holdout"], {"trades": 1, "reached": 1, "finished_positive": 1})
        text = review.drawdown_text(group)
        self.assertIn("3 of its 5 trades since 2010 went that far against; 1 of those 3 finished positive", text)
        self.assertEqual(review.drawdown_group(trade_list(), "QQQ", "rsi2_below_10", "close_above_sma5", "etf_close", 0.01)["status"], "none")
        self.assertEqual(review.drawdown_group(None, "QQQ", "x", "y", "z", -0.1)["status"], "unavailable")
        beyond = review.drawdown_group(trade_list(), "QQQ", "rsi2_below_10", "close_above_sma5", "etf_close", -0.5)
        self.assertIn("beyond every past worst point", review.drawdown_text(beyond))

    def test_the_sizing_arithmetic(self):
        self.assertEqual(review.sizing(None)["text"], "set a loss limit")
        size = review.sizing(0.01, worst_inside=-0.116, leveraged_worst=-0.525, wrong_if_distance=0.03)
        self.assertAlmostEqual(size["at_wrong_if"], 1 / 3)
        self.assertAlmostEqual(size["at_worst_1x"], 0.01 / 0.116)
        self.assertAlmostEqual(size["at_worst_leveraged"], 0.01 / 0.525)
        self.assertIn("33.3% of the account loses 1.00%", size["text"])
        self.assertIsNone(review.sizing(0.01, -0.1)["at_wrong_if"])
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for risk, expected in (({"max_loss_per_trade": 0.005}, 0.005),
                                   ({"max_loss_per_trade": 500, "account_equity": 50000}, 0.01),
                                   ({"max_loss_per_trade": 500, "account_equity": None}, None),
                                   ({"max_loss_per_trade": None}, None)):
                with mock.patch("terminal_config.load_config", return_value={"risk": risk}):
                    self.assertEqual(review.loss_limit(root)["fraction"], expected)

    def test_open_rule_trades_with_their_worst_point_and_time_stop(self):
        closes = list(np.linspace(150, 120, 80)) + [100.0, 98.0, 97.0]
        f = frame(closes, start="2026-07-01")
        day = f"{f.index[-3]:%Y-%m-%d}"
        sig = [{"symbol": "QQQ", "signal": "rsi2_below_10", "label": "RSI(2) below 10", "recent_fired": [day],
                "evidence": [{"verdict": "Lead", "mode": "etf_close", "exit": "close_above_sma5"},
                             {"verdict": "No edge", "mode": "etf_next_open", "exit": "close_above_sma5"}]}]
        [t] = paper_book.rule_trades({"QQQ": f}, sig)
        self.assertEqual((t["status"], t["entry_price"], t["mode"]), ("open", 100.0, "etf_close"))
        self.assertAlmostEqual(t["worst_so_far"], 96.0 / 100 - 1)  # lowest low after the entry close
        self.assertEqual(t["time_stop"], review.sessions_after(day, 10)[-1])
        trades = review.rule_trades({"rule_trades": [t], "paper_book": {"trades": []}}, trade_list())
        self.assertEqual(trades[0]["label"], "rule trade, not a stance")
        self.assertEqual(trades[0]["drawdown_group"]["development"]["reached"], 3)  # mae at or below -4%


class LevelsAndTimingTests(unittest.TestCase):
    def test_near_a_trigger_scales_with_atr(self):
        sigs = [{"symbol": "QQQ", "signal": "x", "fired": False, "trigger_close": 97.0, "close": 100.0},
                {"symbol": "SPY", "signal": "x", "fired": False, "trigger_close": 97.5, "close": 100.0}]
        evidence_cards.attach(sigs, {"status": "unavailable"}, {"QQQ": 2.5, "SPY": 1.0})
        self.assertTrue(sigs[0]["near_trigger"])  # 3 below, 1.2 ATR
        self.assertFalse(sigs[1]["near_trigger"])  # 2.5 below is 2.5 ATR in a calm market, though within 3%
        self.assertAlmostEqual(sigs[0]["near_atr"], 1.2)
        evidence_cards.attach(sigs, {"status": "unavailable"})
        self.assertTrue(sigs[1]["near_trigger"])  # no ATR: the 3% rule
        self.assertEqual(sigs[1]["near_basis"], "within 3%")

    def test_levels_atr_and_swing_points(self):
        closes = [100, 101, 102, 103, 104, 110, 104, 103, 102, 101, 100, 95, 100, 101, 102, 103, 104, 105, 106, 107, 108]
        f = frame(closes)
        out = levels.build({"QQQ": f})["symbols"]["QQQ"]
        self.assertEqual(out["swing_high"]["price"], 111.0)
        self.assertEqual(out["swing_high"]["date"], f"{f.index[5]:%Y-%m-%d}")
        self.assertEqual(out["swing_low"]["price"], 94.0)
        self.assertAlmostEqual(out["exit_close"], np.mean(closes[-4:]))
        self.assertAlmostEqual(out["sma20"], np.mean(closes[-20:]))
        self.assertIsNone(out["sma200"])
        flat = frame([100.0] * 30)  # high - low = 2 every day, no gaps
        self.assertAlmostEqual(levels.atr(flat), 2.0)

    def test_modes(self):
        ny = "America/New_York"
        self.assertEqual(review.mode_for(pd.Timestamp("2026-11-21 10:00", tz=ny)), "weekly")  # Saturday
        self.assertEqual(review.mode_for(pd.Timestamp("2026-11-23 15:40", tz=ny)), "preclose")
        self.assertEqual(review.mode_for(pd.Timestamp("2026-11-23 16:05", tz=ny)), "evening")
        self.assertEqual(review.mode_for(pd.Timestamp("2026-11-27 12:45", tz=ny)), "preclose")  # 1 PM early close
        self.assertEqual(review.mode_for(pd.Timestamp("2026-11-26 15:40", tz=ny)), "evening")  # Thanksgiving

    def test_the_preclose_view_reads_the_live_minute_bars(self):
        from intraday import store
        ny = "America/New_York"
        now = pd.Timestamp("2026-11-23 15:45", tz=ny)
        closes = list(np.linspace(150, 110, 70))
        daily = frame(closes, start="2026-08-17")
        daily = daily[daily.index < "2026-11-23"]
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"APP_OFFLINE": "", "APP_REPLAY": ""}):
            root = Path(tmp)
            bar_time = pd.Timestamp("2026-11-23 15:43", tz=ny).tz_convert("UTC")
            store.ingest_live(root, [{"symbol": "QQQ", "timestamp": bar_time.isoformat(),
                                      "available_at": (bar_time + pd.Timedelta(seconds=65)).isoformat(), "interval_seconds": 60,
                                      "open": 101, "high": 101.5, "low": 100.5, "close": 101.0, "volume": 1000,
                                      "source": "test", "availability_basis": "observed_live"}])
            payload = {"strategies": [], "signal_days": {}}
            built = [{"symbol": "QQQ", "signal": "rsi2_below_10", "trigger_close": 105.0,
                      "evidence": [{"verdict": "Lead", "mode": "etf_close", "exit": "close_above_sma5"}]}]
            with mock.patch("thesis.data.etfs", return_value={"QQQ": daily}), \
                    mock.patch("thesis.signals.load_export", return_value=(payload, {"status": "ok"})), \
                    mock.patch("thesis.signals.build", return_value={"signals": built}):
                out = review.preclose_live(root, now)
        self.assertEqual((out["status"], out["mode"]), ("ok", "preclose"))
        self.assertEqual(out["bars"]["QQQ"]["price"], 101.0)
        self.assertEqual(out["bars"]["QQQ"]["age_seconds"], 60)
        [row] = out["rows"]  # only the close-entry Lead
        self.assertEqual((row["signal"], row["trigger"], row["fired"]), ("rsi2_below_10", 105.0, True))


if __name__ == "__main__":
    unittest.main()
