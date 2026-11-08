"""Daily thesis tab: no look-ahead, rule triggers, evidence cross-check, stance rules, call log, rendering."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from thesis import build, calls, credit, data, earnings, morning, regime, risk, signals, stance_log  # noqa: E402

NY = "America/New_York"
DAYS = pd.bdate_range("2008-01-02", periods=900)


def frame(seed=2, days=DAYS):
    r = np.random.default_rng(seed).normal(0.0004, 0.012, len(days))
    close = pd.Series(100 * np.cumprod(1 + r), index=days)
    return pd.DataFrame({"open": close.shift(1).fillna(100), "high": close * 1.01, "low": close * 0.99,
                         "close": close, "volume": 1e6})


class TimingTests(unittest.TestCase):
    def test_a_daily_bar_counts_only_after_the_close(self):
        self.assertEqual(data.last_known_session(pd.Timestamp("2026-11-09 15:00", tz=NY)), pd.Timestamp("2026-11-08"))
        self.assertEqual(data.last_known_session(pd.Timestamp("2026-11-09 16:20", tz=NY)), pd.Timestamp("2026-11-09"))

    def test_fred_values_wait_a_day(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "x.csv"
            path.write_text("observation_date,X\n2026-11-05,1.5\n2026-11-06,.\n2026-11-09,1.7\n", encoding="utf-8")
            seen = data.fred(path, pd.Timestamp("2026-11-09 17:00", tz=NY))
            self.assertEqual(list(seen.index), [pd.Timestamp("2026-11-05")])  # 11-09 isn't published until later

    def test_view_mode_by_eastern_time(self):
        self.assertEqual(morning.mode(pd.Timestamp("2026-11-09 08:00", tz=NY))["mode"], "morning")
        self.assertEqual(morning.mode(pd.Timestamp("2026-11-09 12:00", tz=NY))["mode"], "session")
        self.assertEqual(morning.mode(pd.Timestamp("2026-11-09 18:00", tz=NY))["mode"], "evening")
        self.assertEqual(morning.mode(pd.Timestamp("2026-11-08 12:00", tz=NY))["mode"], "weekend")


class SignalTests(unittest.TestCase):
    def test_trigger_close_is_the_boundary_of_each_rule(self):
        close = frame()["close"]
        for name, (_, rule, _) in signals.RULES.items():
            level = signals.trigger_close(close, rule)
            self.assertIsNotNone(level, name)
            nxt = close.index[-1] + pd.Timedelta(days=1)
            fires = lambda p: bool(rule(pd.concat([close, pd.Series([p], index=[nxt])])).iloc[-1])  # noqa: E731
            self.assertTrue(fires(level), name)
            self.assertFalse(fires(level * 1.002), name)

    def test_rsi_definition(self):
        close = pd.Series([10, 11, 12, 11, 13, 12, 14], dtype=float)
        value = signals.rsi(close, 2)
        self.assertTrue(value.iloc[:2].isna().all())
        self.assertTrue(((value.dropna() >= 0) & (value.dropna() <= 100)).all())
        self.assertEqual(signals.rsi(pd.Series([1, 2, 3, 4, 5], dtype=float), 2).iloc[-1], 100.0)

    def test_crosscheck_reports_definition_drift(self):
        fired = pd.Series([False, True, False, True], index=pd.bdate_range("2020-01-01", periods=4))
        same = {"last_date": "2020-01-06", "dates": ["2020-01-02", "2020-01-06"]}
        self.assertEqual(signals.crosscheck(fired, same)["status"], "match")
        drift = {"last_date": "2020-01-06", "dates": ["2020-01-02"]}
        self.assertEqual(signals.crosscheck(fired, drift)["differences"], ["2020-01-06"])
        later = {"last_date": "2020-01-03", "dates": ["2020-01-02"]}  # dates after the export's data are not compared
        self.assertEqual(signals.crosscheck(fired, later)["status"], "match")

    def test_missing_export_is_unavailable_not_an_error(self):
        payload, info = signals.load_export(Path(tempfile.gettempdir()) / "no-such-export.json")
        self.assertIsNone(payload)
        self.assertEqual(info["status"], "unavailable")


def lead(symbol, signal, exit_name="close_above_sma5", verdict="Lead"):
    period = {"trades": 90, "win_rate": 0.7, "mean_net": 0.005, "random_percentile": 97, "avg_loss": -0.02,
              "strategy": {"cagr": 0.03, "max_drawdown": -0.2, "return_per_drawdown": 0.15},
              "matched": {"cagr": 0.01, "max_drawdown": -0.03, "return_per_drawdown": 0.33}}
    return {"symbol": symbol, "signal": signal, "exit": exit_name, "mode": "etf_next_open", "verdict": verdict,
            "exit_label": exit_name, "mode_label": "Buy at the next open", "development": period, "holdout": period}


def signal_row(symbol, fired, evidence):
    return {"symbol": symbol, "signal": "bollinger_lower_close", "label": "Close below band", "fired": fired,
            "close": 100.0, "trigger_close": 98.0, "sma5": 101.0, "evidence": evidence}


REGIME = {"events": {"upcoming": [{"date": "2026-11-10", "label": "CPI"}]}, "volatility": {"term_ratio": 0.9}}


class StanceTests(unittest.TestCase):
    def test_flat_when_nothing_registered_fired(self):
        s = build.stance([signal_row("SPY", False, [lead("SPY", "x")])], REGIME, {"rows": []}, "2026-11-06")
        self.assertEqual(s["direction"], "flat")
        self.assertEqual(s["changes"][0]["close_at_or_below"], 98.0)
        self.assertIn("CPI 2026-11-10", s["cautions"][0])

    def test_long_only_with_a_lead(self):
        weak = build.stance([signal_row("SPY", True, [lead("SPY", "x", verdict="No edge")])], REGIME, {"rows": []}, "2026-11-06")
        self.assertEqual(weak["direction"], "flat")
        strong = build.stance([signal_row("QQQ", True, [lead("QQQ", "x")])], REGIME, {"rows": []}, "2026-11-06")
        self.assertEqual(strong["direction"], "long")
        self.assertIn("did better in 2010-2026 for 1 of these 1", strong["cautions"][0])
        self.assertTrue(any("5-day average" in e for e in strong["exit"]))

    def test_never_short(self):
        for fired in (True, False):
            s = build.stance([signal_row("SPY", fired, [lead("SPY", "x")])], REGIME, {"rows": []}, "2026-11-06")
            self.assertNotEqual(s["direction"], "short")


class RegimeAndRiskTests(unittest.TestCase):
    def test_vix_buckets_and_history(self):
        self.assertEqual(regime.vix_bucket(14.99), "VIX below 15")
        self.assertEqual(regime.vix_bucket(30.0), "VIX 30 and up")
        f = frame(days=pd.bdate_range("1995-01-02", periods=7000))
        vix = pd.Series(18.0, index=f.index)
        out = regime.regime_history(f, vix)
        self.assertEqual(out["status"], "ok")
        dev = out["periods"][0]
        span = int((f.index >= regime.DEVELOPMENT_START).sum())
        self.assertLessEqual(dev["similar_independent_20"], min(dev["similar_days_20"], span // 20 + 1))
        self.assertLessEqual(dev["all_independent_20"], span // 20 + 1)

    def test_leverage_losses_cap_at_the_whole_account(self):
        rows = risk.leverage_rows(0.01, {"p01_1d": -0.03, "worst_1d": -0.2, "worst_5d": -0.3})
        ten = rows[-1]
        self.assertEqual(ten["leverage"], 10)
        self.assertEqual(ten["worst_day"], -1.0)
        self.assertAlmostEqual(ten["index_move_to_lose_all"], -0.1)
        self.assertAlmostEqual(rows[0]["one_sd_day"], 0.01)

    def test_move_history_uses_the_prior_close_vix(self):
        f = frame(days=pd.bdate_range("2000-01-03", periods=400))
        vix = pd.Series(np.where(np.arange(400) % 2, 25.0, 12.0), index=f.index)
        out = risk.move_history(f, vix, 25.0)
        self.assertEqual(out["status"], "ok")
        self.assertEqual(out["days"], 199)  # days after a 25 close (the first day has no prior close)


class CallLogTests(unittest.TestCase):
    def test_validation(self):
        good = {"instrument": "spy", "direction": "long", "horizon_sessions": "5", "invalidation": "close < 700"}
        self.assertEqual(calls.validate(good)["instrument"], "SPY")
        for bad in ({**good, "instrument": "TSLA"}, {**good, "direction": "sideways"}, {**good, "horizon_sessions": 0},
                    {**good, "horizon_sessions": 61}, {**good, "invalidation": ""}, {**good, "reason": "x" * 1501}):
            with self.assertRaises(ValueError):
                calls.validate(bad)
        self.assertEqual(calls.validate({**good, "direction": "flat", "invalidation": ""})["direction"], "flat")

    def test_chain_appends_and_detects_edits(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = {"instrument": "QQQ", "direction": "short", "horizon_sessions": 3, "invalidation": "x"}
            calls.append(root, base, pd.Timestamp("2026-11-09 22:00", tz="UTC"))
            calls.append(root, {**base, "direction": "long"}, pd.Timestamp("2026-11-10 22:00", tz="UTC"))
            self.assertEqual(calls.verify(root), {"ok": True, "calls": 2})
            path = root / calls.LOG
            path.write_text(path.read_text(encoding="utf-8").replace('"short"', '"long"'), encoding="utf-8")
            self.assertFalse(calls.verify(root)["ok"])
            with self.assertRaises(ValueError):
                calls.append(root, base)

    def test_entry_is_the_next_open_and_scores_both_directions(self):
        days = pd.bdate_range("2026-11-02", periods=10)
        f = pd.DataFrame({"open": np.arange(100, 110, dtype=float), "close": np.arange(101, 111, dtype=float)}, index=days)
        evening = pd.Timestamp("2026-11-03 17:00", tz=NY)
        self.assertEqual(days[calls.entry_position(days, evening)], pd.Timestamp("2026-11-04"))
        morning_call = pd.Timestamp("2026-11-03 09:00", tz=NY)
        self.assertEqual(days[calls.entry_position(days, morning_call)], pd.Timestamp("2026-11-03"))
        long = {"id": 1, "recorded_et": evening.isoformat(), "instrument": "SPY", "direction": "long", "horizon_sessions": 2}
        s = calls.score(long, f)
        self.assertEqual((s["status"], s["entry_date"], s["through_date"]), ("scored", "2026-11-04", "2026-11-05"))
        self.assertAlmostEqual(s["call_return"], 104 / 102 - 1)
        short = calls.score({**long, "direction": "short"}, f)
        self.assertAlmostEqual(short["call_return"], -(104 / 102 - 1))
        self.assertAlmostEqual(short["versus_always_long"], -2 * (104 / 102 - 1))
        flat = calls.score({**long, "direction": "flat"}, f)
        self.assertEqual(flat["call_return"], 0)
        late = calls.score({**long, "recorded_et": pd.Timestamp("2026-11-13 18:00", tz=NY).isoformat()}, f)
        self.assertEqual(late["status"], "pending")
        board = calls.scoreboard([s, short, flat])
        self.assertEqual((board["scored"], board["directional_scored"], board["hit_rate"]), (3, 2, 0.5))


def page_state(fired_spy=True, evidence="ok", mismatch=False):
    rows = []
    for symbol in ("SPY", "QQQ"):
        rows.append({**signal_row(symbol, fired_spy and symbol == "SPY", [lead(symbol, "x")]),
                     "crosscheck": {"status": "mismatch" if mismatch else "match"}})
    return {"latest_close": "2026-11-06", "evidence_source": {"status": evidence, "sha256": "abc"},
            "signals": rows, "stance": {"headline": "Long candidate"}}


def next_open(session):
    return pd.Timestamp("2026-11-09 09:30", tz=NY)  # the session after Fri 2026-11-06


class StanceLogTests(unittest.TestCase):
    def test_records_follow_the_stance_rules(self):
        records, reason = stance_log.records_for(page_state())
        self.assertIsNone(reason)
        self.assertEqual([(r["instrument"], r["direction"]) for r in records], [("SPY", "long"), ("QQQ", "flat")])
        self.assertEqual(stance_log.records_for(page_state(evidence="unavailable"))[0], [])
        self.assertIn("no longer match", stance_log.records_for(page_state(mismatch=True))[1])

    def test_logged_once_per_close_and_only_before_the_next_open(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            evening = pd.Timestamp("2026-11-06 18:00", tz=NY)
            first = stance_log.append_daily(root, page_state(), evening, entry_time=next_open)
            self.assertEqual(first["logged"], 2)
            again = stance_log.append_daily(root, page_state(fired_spy=False), evening, entry_time=next_open)
            self.assertEqual(again["logged"], 0)  # the first record for a close stands
            late = stance_log.append_daily(root, {**page_state(), "latest_close": "2026-11-05"},
                                           pd.Timestamp("2026-11-09 10:00", tz=NY), entry_time=next_open)
            self.assertIn("too late", late["skipped"])
            self.assertEqual(calls.verify(root, stance_log.LOG), {"ok": True, "calls": 2})
            self.assertFalse((root / calls.LOG).exists())  # the user's call log is separate

    def test_scored_like_a_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            stance_log.append_daily(root, page_state(), pd.Timestamp("2026-11-06 18:00", tz=NY), entry_time=next_open)
            days = pd.bdate_range("2026-11-02", periods=15)
            f = pd.DataFrame({"open": np.arange(100, 115, dtype=float), "close": np.arange(101, 116, dtype=float)}, index=days)
            out = stance_log.summary(root, {"SPY": f, "QQQ": f})
            spy = next(r for r in out["records"] if r["instrument"] == "SPY")
            self.assertEqual((spy["status"], spy["entry_date"], spy["through_date"]), ("scored", "2026-11-09", "2026-11-13"))
            self.assertAlmostEqual(spy["call_return"], 110 / 105 - 1)  # Nov 9 open to Nov 13 close
            qqq = next(r for r in out["records"] if r["instrument"] == "QQQ")
            self.assertEqual(qqq["call_return"], 0)
            self.assertEqual((out["scoreboard"]["scored"], out["long_scored"]), (2, 1))

    def test_offline_state_build_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state = build.build_state(root, pd.Timestamp("2026-11-08 12:00", tz=NY))
            self.assertEqual(state["stance_log"]["scoreboard"]["calls"], 0)
            self.assertEqual([p for p in root.rglob("*") if p.is_file()], [])


class SourceTests(unittest.TestCase):
    def test_credit_refresh_keeps_the_previous_copy_on_bad_data(self):
        class Reply:
            def __init__(self, text):
                self.text = text

            def raise_for_status(self):
                pass
        good = "observation_date,V\n" + "\n".join(f"{d:%Y-%m-%d},{1.5 + i / 1000}" for i, d in enumerate(pd.bdate_range("2020-01-01", periods=300)))
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertTrue(all(s["ok"] for s in credit.refresh(root, get=lambda *a, **k: Reply(good)).values()))
            status = credit.refresh(root, get=lambda *a, **k: Reply("observation_date,V\n2020-01-01,999\n"))
            self.assertFalse(any(s["ok"] for s in status.values()))
            self.assertEqual(len(credit.load(root, pd.Timestamp("2026-01-01", tz=NY))["BAA10Y"]), 300)

    def test_earnings_reaction_session_and_source_failures(self):
        index = pd.bdate_range("2026-11-16", periods=5)
        self.assertEqual(earnings.reaction_session(index, "2026-11-17", "16:00", None), pd.Timestamp("2026-11-18"))
        self.assertEqual(earnings.reaction_session(index, "2026-11-17", "07:00", None), pd.Timestamp("2026-11-17"))
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            yahoo = lambda s: [{"date": "2026-11-17", "time_et": "16:00"}]  # noqa: E731

            def broken(symbol):
                raise RuntimeError("blocked")
            earnings.refresh(root, yahoo=yahoo, nasdaq=lambda s: {"date": "2026-11-18", "timing": "after close"}, pause=0)
            earnings.refresh(root, yahoo=broken, nasdaq=lambda s: {"date": "2026-11-17", "timing": "after close"}, pause=0)
            saved = json.loads((root / earnings.FILE).read_text(encoding="utf-8"))["companies"]["NVDA"]
            self.assertEqual((saved["yahoo_ok"], saved["yahoo"][0]["date"]), (False, "2026-11-17"))  # last good copy kept
            etfs = {"QQQ": frame(days=pd.bdate_range("2026-01-02", periods=200))}
            out = earnings.build(root, pd.Timestamp("2026-11-08 12:00", tz=NY), etfs)
            nvda = next(r for r in out["rows"] if r["symbol"] == "NVDA")
            self.assertEqual((nvda["agreement"], nvda["next_date"]), ("agree", "2026-11-17"))


class RenderTests(unittest.TestCase):
    def test_render_escapes_source_text_and_replaces_placeholders(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            state = {"schema_version": 1, "as_of": "2026-11-08T12:00:00-05:00", "stance": {"headline": "</script><b>x"},
                     "evidence_source": {"sha256": "abc"}, "bad": float("nan")}
            page = build.render(Path(tmp), out, state).read_text(encoding="utf-8")
            self.assertNotIn("{{", page)
            self.assertNotIn("</script><b>", page)
            self.assertIn('aria-current="page">Daily thesis', page)
            saved = json.loads((out / "thesis_state.json").read_text(encoding="utf-8"))
            self.assertIsNone(saved["bad"])
            self.assertEqual(json.loads((out / "manifest_thesis.json").read_text(encoding="utf-8"))["component"], "thesis")


if __name__ == "__main__":
    unittest.main()
