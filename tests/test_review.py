"""The Review page (2026-11-19, approved by the user): callouts from the thesis build and optional backtester files."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from thesis import review  # noqa: E402

LEAD = {"mode": "etf_next_open", "verdict": "Lead", "exit": "close_above_sma5",
        "exit_label": "First close above the 5-day average (max 10)", "forward": {"trades": 1, "status": "too few"}}


def state(direction="long", fired=True):
    return {"as_of": "2026-11-20T18:00:00-05:00", "latest_close": "2026-11-20", "next_entry_et": "2026-11-23T09:30:00-05:00",
            "stance": {"direction": direction, "headline": "Long candidate" if direction == "long" else "Flat",
                       "basis": [{"symbol": "QQQ", "rule": "Close below the lower Bollinger band (20, 2)",
                                  "exit": "First close above the 5-day average (max 10)", "dev_trades": 104}] if direction == "long" else []},
            "signals": [{"symbol": "QQQ", "signal": "bollinger_lower_close", "label": "Close below the lower Bollinger band (20, 2)",
                         "fired": fired, "near_trigger": not fired, "close": 640.0, "trigger_close": 645.0 if fired else 630.0,
                         "value": 642.0, "sma5": 655.0, "evidence": [LEAD],
                         "cards": [{"exit": "close_above_sma5", "trades_per_year": 6.0}]}],
            "regime": {"volatility": {"vix": 26.0, "level": "elevated", "term_ratio": 1.02},
                       "events": {"upcoming": [{"date": "2026-11-24", "label": "Jobs report"}]},
                       "trend": {"QQQ": {"close": 640.0, "sma50": 700.0, "sma200": 680.0}}},
            "earnings": {"rows": []}, "ops": {"rows": [{"label": "Live minute bars", "state": "late", "detail": "gap"}]},
            "evidence_check": {"age_days": 3, "checked_through": "2026-11-17"},
            "paper_book": {"trades": [], "ticket": [{"action": "enter", "text": "Enter: paper long QQQ"}]},
            "calls": {"calls": [{"relation": "take", "status": "scored", "call_return": 0.02}]},
            "stance_log": {"missed_closes": ["2026-11-16"]}, "ideas": {"ideas": [], "counts": {}}}


class ReviewTests(unittest.TestCase):
    def test_a_long_setup_gives_a_plan_without_assuming_a_loss_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = review.build(state(), Path(tmp), export_dir=Path(tmp) / "missing")  # no backtester files at all
        [plan] = out["today"]["plan"]
        self.assertEqual((plan["symbol"], plan["loss_at_limit"]), ("QQQ", "set a loss limit"))
        self.assertIn("5-day average", plan["exit_rule"])
        self.assertIn("$655.00", plan["exit_level"])
        levels = {c["level"] for c in out["headline"]}
        self.assertIn("act", levels)
        texts = " ".join(c["text"] for c in out["headline"])
        self.assertIn("Set a loss limit", texts)
        self.assertIn("weekend or holiday", texts)  # Friday close, Monday open
        self.assertIn("Jobs report", texts)
        self.assertTrue(all(c.get("source") for c in out["headline"]))
        self.assertIn("not found", " ".join(c["text"] for c in out["changes"]["callouts"]))
        self.assertEqual(out["record"]["calls_by_relation"]["take"]["scored"], 1)
        self.assertEqual(out["queue"]["forward_checks"][0]["months_to_check"], 8)  # 4 more trades at 6 a year

    def test_a_near_trigger_lead_is_a_watch_and_filter_tests_are_one_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            exports = Path(tmp)
            (exports / "filter_tests.json").write_text(json.dumps({"generated_at": "2026-11-18T07:08:30+00:00", "tests": [
                {"test": "vix_level", "strategy": "QQQ:x|etf_next_open", "group_label": "VIX 20 or higher", "label": "Too few trades"},
                {"test": "gap", "strategy": "QQQ:x|etf_next_open", "group_label": None, "label": "Insufficient evidence"}]}),
                encoding="utf-8")
            (exports / "trade_simulation.json").write_text(json.dumps({"verdict_changes": []}), encoding="utf-8")
            out = review.build(state("flat", fired=False), exports, export_dir=exports)
        watch = [c["text"] for c in out["today"]["callouts"] if c["level"] == "watch"]
        self.assertTrue(any("closes at or below $630.00" in t for t in watch))
        filters = [c for c in out["changes"]["callouts"] if "Filter tests" in c["text"]]
        self.assertEqual(len(filters), 1)
        self.assertEqual(filters[0]["level"], "info")
        self.assertEqual(len(out["changes"]["filter_tests"]["notable"]), 1)


if __name__ == "__main__":
    unittest.main()
