"""2026-11-18 (backtester hand-off, user: "Build all three"): the daily archive, stances scored to the rule's own
exit, evidence cards from evidence.json, and rounding ties in the date cross-check."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from thesis import archive, build, calls, eligibility, evidence_cards, ops, signals, stance_log  # noqa: E402

NY = "America/New_York"
EVENING = pd.Timestamp("2026-11-17 21:40", tz=NY)
OPEN = lambda day: pd.Timestamp("2026-11-18 09:30", tz=NY)  # noqa: E731


def page_state():
    return {"latest_close": "2026-11-17", "as_of": EVENING.isoformat(),
            "stance": {"direction": "flat", "status": "close_only_setup", "headline": "Flat", "cautions": ["x"]},
            "evidence_source": {"status": "ok", "verdict_version": "v3", "sha256": "abc"},
            "evidence_check": {"status": "ok", "usable": True, "checked_through": "2026-11-17", "age_days": 0},
            "regime": {"history": {"condition": "SPY above its 200-day average, VIX 20-30"},
                       "volatility": {"vix": np.float64(25.46), "vix3m": 24.98, "term_ratio": 1.0192, "bucket": "VIX 20-30",
                                      "date": "2026-11-17", "change_5d": np.int64(6)},
                       "trend": {"SPY": {"close": 732.44, "vs_sma50": -0.02, "vs_sma200": 0.03, "return_20d": -0.01, "state": "x"}},
                       "credit": [{"series": "BAA10Y", "value": 1.5, "change_1m": 0.06, "date": "2026-11-16", "label": "x"}],
                       "rates": {"curve": 0.29, "ten_year": 5.12, "two_year": 4.83, "date": "2026-11-16"},
                       "breadth": {"relative_20d": 0.047, "relative_60d": 0.014, "date": "2026-11-17", "reading": "x"},
                       "events": {"upcoming": [{"date": "2026-11-20", "label": "Jobs report"}, {"date": "2026-12-10", "label": "CPI"}]}},
            "earnings": {"rows": [{"name": "Nvidia", "next_date": "2026-11-19"}, {"name": "Broadcom", "next_date": "2026-12-09"}]},
            "earnings_calendar": {"days": [{"date": "2026-11-18", "rows": [{"symbol": "PANW"}]}, {"date": "2026-11-30", "rows": [{"symbol": "X"}]}]},
            "news": {"count": 15, "since": "2026-11-17 16:00", "last_collected_et": "2026-11-17 16:05", "rows": [1, 2]},
            "view": {"mode": "evening", "futures": {"status": "unavailable", "rows": []}},
            "movers": {"flagged": [{"name": "Nvidia", "move": -0.051}]},
            "signals": [{"symbol": "QQQ", "signal": "rsi2_below_10", "fired": np.bool_(True), "value": 5.5, "close": 656.95,
                         "trigger_close": 657.2, "evidence": [{"mode": "etf_next_open", "verdict": "No edge"},
                                                              {"mode": "etf_close", "verdict": "Lead"}]}]}


class ArchiveTests(unittest.TestCase):
    def test_one_strict_json_record_per_close_before_the_next_open(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertEqual(archive.append_daily(root, page_state(), EVENING, OPEN)["logged"], 1)
            self.assertIn("already archived", archive.append_daily(root, page_state(), EVENING, OPEN)["skipped"])
            later = page_state() | {"latest_close": "2026-11-18"}
            self.assertIn("too late", archive.append_daily(root, later, pd.Timestamp("2026-11-19 10:00", tz=NY),
                                                            lambda day: pd.Timestamp("2026-11-19 09:30", tz=NY))["skipped"])
            line = (root / archive.LOG).read_text(encoding="utf-8")
            json.loads(line, parse_constant=lambda c: self.fail(f"non-strict JSON: {c}"))
            [row] = calls.read(root, archive.LOG)  # hash-chained, like the stance log
            self.assertEqual((row["latest_close"], row["volatility"]["vix"], row["volatility"]["change_5d"]), ("2026-11-17", 25.46, 6))
            self.assertEqual(row["events_next_5"], [{"date": "2026-11-20", "label": "Jobs report"}])  # CPI is outside 5 sessions
            self.assertEqual(row["mega_cap_earnings_next_5"], [{"date": "2026-11-19", "name": "Nvidia"}])
            self.assertEqual(row["earnings_calendar_next_5"], [{"date": "2026-11-18", "symbols": ["PANW"]}])
            rule = row["rules"][0]
            self.assertEqual((rule["fired"], rule["next_open_verdicts"]), (True, ["No edge"]))
            self.assertAlmostEqual(rule["distance"], 657.2 / 656.95 - 1)
            self.assertEqual(row["news"]["count"], 15)
            self.assertEqual(archive.summary(root), {"status": "ok", "count": 1, "first": "2026-11-17", "last": "2026-11-17"})
            status = ops.build(root, EVENING, "2026-11-17")
            self.assertEqual([r["state"] for r in status["rows"] if r["label"] == "Daily archive"], ["ok"])

    def test_it_shares_the_stance_logs_gate(self):
        with patch.dict(os.environ, {"APP_OFFLINE": "0", "APP_REPLAY": "0", "APP_NO_RECORD": "1"}):
            self.assertFalse(build.recording_requested())  # run_thesis archives only when this is True


class RuleExitScoreTests(unittest.TestCase):
    def test_a_long_record_is_also_scored_to_its_rules_exit(self):
        days = pd.bdate_range("2026-11-02", periods=12)
        close = [100, 99, 98, 97, 96, 97, 98, 103, 104, 105, 106, 107]
        frame = pd.DataFrame({"open": [c - 0.5 for c in close], "close": close}, index=days, dtype=float)
        record = {"latest_close": "2026-11-06", "instrument": "QQQ", "direction": "long", "rules": ["rsi14_below_30"],
                  "rule_exits": {"rsi14_below_30": ["close_above_sma5"]}, "stance_rules": 2}
        out = stance_log.rule_exit(record, {"QQQ": frame}, [])
        self.assertEqual(out["status"], "closed")
        # bought at the Nov 9 open (96.5); first close above the 5-day average is Nov 9's 97 (> 97.4? no) ... Nov 10's 98
        leg = out["legs"][0]
        self.assertEqual(leg["exit"], "close_above_sma5")
        self.assertAlmostEqual(out["net"], frame.loc[leg["exit_date"], "close"] / 96.5 - 1 - 0.0002)
        self.assertIsNone(stance_log.rule_exit({**record, "direction": "flat"}, {"QQQ": frame}, []))


def card(symbol="QQQ", signal="bollinger_lower_close@v1", exit_name="close_above_sma5@v1", entry="etf_next_open", verdict="Lead"):
    return {"strategy": "x", "symbol": symbol, "signal": signal, "exit": exit_name, "entry": entry, "verdict": verdict,
            "trades": 104, "occurrence": {"trades_per_year": 6.17}, "excess": 0.006, "excess_ci90": [0.002, 0.009],
            "mean_net": 0.0079, "inside_trades": {"mae_worst": -0.197, "mae_p10": -0.055},
            "net_distribution": {"worst_net": -0.15}, "holdout": {"trades": 66, "excess": 0.009, "p": 0.05},
            "leveraged": {"instrument": "TQQQ", "trades": 102, "mean_net": 0.021, "worst_net": -0.476, "mae_worst": -0.525},
            "forward": {"since": "2026-11-13", "trades": 0, "status": "none yet"}, "limitations": ["Daily bars"],
            "ideas": [{"id": 2}]}


class EvidenceCardTests(unittest.TestCase):
    def load(self, payload, info=None):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "evidence.json"
            if payload is not None:
                path.write_text(json.dumps(payload) if not isinstance(payload, str) else payload, encoding="utf-8")
            return evidence_cards.load(info, path)

    def test_cards_attach_to_fired_and_near_rules_and_damage_is_unavailable(self):
        good = {"kind": "evidence", "schema": 1, "cards": [card(), card(entry="etf_close"), card(signal="rsi2_below_10@v1")],
                "generated_from": {"trade_simulation": {"generated_at": "2026-11-18T07:08:04+00:00"}}}
        loaded = self.load(good, {"status": "ok", "generated_at": "2026-11-18T07:08:04+00:00"})
        self.assertEqual((loaded["status"], loaded["same_run"]), ("ok", True))
        self.assertFalse(self.load(good, {"status": "ok", "generated_at": "2026-11-11T00:00:00+00:00"})["same_run"])
        sigs = [{"symbol": "QQQ", "signal": "bollinger_lower_close", "fired": False, "close": 100.0, "trigger_close": 98.0},
                {"symbol": "QQQ", "signal": "rsi14_below_30", "fired": False, "close": 100.0, "trigger_close": 90.0}]
        evidence_cards.attach(sigs, loaded)
        boll, rsi = sigs
        self.assertEqual((boll["near_trigger"], rsi["near_trigger"]), (True, False))  # 2% away vs 10% away
        self.assertEqual([c["entry"] for c in boll["cards"]], ["etf_next_open"])  # the entry still available
        c = boll["cards"][0]
        self.assertEqual((c["exit"], c["leveraged"]["instrument"], c["worst_inside"], c["excess_ci90"]),
                         ("close_above_sma5", "TQQQ", -0.197, [0.002, 0.009]))
        self.assertEqual(rsi["cards"], [])
        self.assertEqual(self.load(None)["status"], "unavailable")
        for bad in ("{not json", {"kind": "evidence", "schema": 2, "cards": [card()]},
                    {"kind": "evidence", "schema": 1, "cards": [{**card(), "trades": "many"}]},
                    {"kind": "evidence", "schema": 1, "cards": [{**card(), "excess_ci90": [1]}]}):
            out = self.load(bad)
            self.assertEqual((out["status"], out["cards"]), ("invalid", []))
            evidence_cards.attach(sigs, out)
            self.assertEqual(sigs[0]["cards"], [])
        self.assertNotIn("cards", evidence_cards.meta(loaded))


class RoundingTieTests(unittest.TestCase):
    def test_a_date_that_differs_only_on_the_threshold_is_tolerated_and_said(self):
        days = pd.bdate_range("2026-01-05", periods=6)
        close = pd.Series([99.0, 101.0, 100.0, 102.0, 98.0, 103.0], index=days)
        rule = lambda c: c >= 100.0  # noqa: E731  (fires at exactly 100: a tie)
        fired = rule(close)
        ours = [f"{d:%Y-%m-%d}" for d in days[fired.to_numpy()]]
        theirs = [d for d in ours if d != "2026-01-07"]  # the backtester's copy had 99.9999 that day
        out = signals.crosscheck(fired, {"last_date": "2026-01-12", "dates": theirs}, close, rule)
        self.assertEqual((out["status"], out["ties"], out["differences"]), ("match", ["2026-01-07"], []))
        real = signals.crosscheck(fired, {"last_date": "2026-01-12", "dates": [d for d in ours if d != "2026-01-06"]}, close, rule)
        self.assertEqual((real["status"], real["differences"]), ("mismatch", ["2026-01-06"]))  # 101 is not a tie
        self.assertEqual(signals.crosscheck(fired, {"last_date": "2026-01-12", "dates": theirs})["status"], "mismatch")
        sig = [{"symbol": s, "signal": "r", "evidence": [{}], "crosscheck": {**out, "checked_through": "2026-01-12"}} for s in ("SPY", "QQQ")]
        check = eligibility.evidence_check({"status": "ok"}, sig, "2026-01-12")
        self.assertTrue(check["usable"])
        self.assertIn("SPY r on 2026-01-07", check["notes"][0])
        page = build.stance([], {"events": {"upcoming": []}, "volatility": {}}, {}, "2026-01-12", check)
        self.assertTrue(any("Tolerated, not a mismatch" in c for c in page["cautions"]))


if __name__ == "__main__":
    unittest.main()
