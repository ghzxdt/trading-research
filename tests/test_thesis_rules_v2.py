"""Stance rules v2 (shared page/log eligibility), export validation, status rows, journal and idea ledger."""
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from thesis import build, calls, eligibility, journal, ledger, ops, signals, stance_log  # noqa: E402

NY = "America/New_York"
REGIME = {"events": {"upcoming": []}, "volatility": {}}
PERIOD = {"trades": 90, "win_rate": 0.7, "mean_net": 0.005, "random_percentile": 97, "avg_loss": -0.02,
          "strategy": {"cagr": 0.03, "max_drawdown": -0.2, "return_per_drawdown": 0.15},
          "matched": {"cagr": 0.01, "max_drawdown": -0.03, "return_per_drawdown": 0.33}}


def row(mode, verdict, exit_name="hold_5"):
    return {"symbol": "SPY", "signal": "rsi2_below_10", "exit": exit_name, "mode": mode, "verdict": verdict,
            "exit_label": exit_name, "mode_label": mode, "development": PERIOD, "holdout": PERIOD}


def signal(symbol, fired, evidence, through="2026-11-06", status="match", name="rsi2_below_10"):
    return {"symbol": symbol, "signal": name, "label": "RSI(2) below 10", "fired": fired, "close": 100.0,
            "trigger_close": 98.0, "sma5": 101.0, "evidence": evidence,
            "crosscheck": {"status": status, "checked_through": through}}


CLOSE_ONLY = [row("etf_close", "Lead"), row("etf_next_open", "No edge")]
BOTH = [row("etf_close", "Lead"), row("etf_next_open", "Lead")]
OK = {"status": "ok", "sha256": "abc"}


def state(spy, qqq=None, source=OK, latest="2026-11-12"):
    sig = [spy, qqq or signal("QQQ", False, BOTH)]
    return {"latest_close": latest, "evidence_source": source, "signals": sig, "stance": {}}


class SharedRuleTests(unittest.TestCase):
    def both(self, st):
        check = eligibility.evidence_check(st["evidence_source"], st["signals"], st["latest_close"])
        page = build.stance(st["signals"], REGIME, {}, st["latest_close"], check)
        return page, stance_log.records_for(st)

    def test_a_lead_only_at_the_close_is_flat_on_the_page_and_in_the_log(self):
        page, (records, reason) = self.both(state(signal("SPY", True, CLOSE_ONLY)))
        self.assertEqual((page["direction"], page["status"]), ("flat", "close_only_setup"))
        self.assertIn("No edge", page["close_only"][0])
        self.assertIsNone(reason)
        spy = records[0]
        self.assertEqual((spy["direction"], spy["rules"], spy["close_only_rules"]), ("flat", [], ["rsi2_below_10"]))
        self.assertEqual(page["changes"], [{"symbol": "QQQ", "rule": "RSI(2) below 10", "close_at_or_below": 98.0,
                                            "distance": 98.0 / 100.0 - 1}])  # only next-open Leads can change the call

    def test_a_next_open_lead_is_long_and_shows_only_that_pricing(self):
        page, (records, _) = self.both(state(signal("SPY", True, BOTH)))
        self.assertEqual(page["direction"], "long")
        self.assertEqual([b["mode"] for b in page["basis"]], ["etf_next_open"])
        self.assertEqual(records[0]["direction"], "long")

    def test_unusable_evidence_is_no_call_on_the_page_and_skipped_in_the_log(self):
        cases = {"unavailable": state(signal("SPY", True, BOTH), source={"status": "unavailable", "reason": "not found"}),
                 "mismatch": state(signal("SPY", True, BOTH, status="mismatch")),
                 "unchecked": state(signal("SPY", True, BOTH, status="unavailable")),
                 "partial": state(signal("SPY", True, [])),
                 "stale": state(signal("SPY", True, BOTH, through="2026-09-01"), signal("QQQ", False, BOTH, through="2026-09-01"))}
        for name, st in cases.items():
            page, (records, reason) = self.both(st)
            self.assertEqual((page["direction"], page["status"], records), ("none", "evidence_unavailable", []), name)
            self.assertTrue(reason, name)
            self.assertEqual(eligibility.evidence_check(st["evidence_source"], st["signals"], st["latest_close"])["status"], name)

    def test_older_evidence_is_used_with_a_caution(self):
        st = state(signal("SPY", True, BOTH, through="2026-10-30"), signal("QQQ", False, BOTH, through="2026-10-30"))
        check = eligibility.evidence_check(st["evidence_source"], st["signals"], st["latest_close"])
        self.assertTrue(check["usable"])
        self.assertEqual(check["age_days"], 13)
        page = build.stance(st["signals"], REGIME, {}, st["latest_close"], check)
        self.assertEqual(page["direction"], "long")
        self.assertTrue(any("13 days old" in c for c in page["cautions"]))

    def test_the_page_says_when_the_entry_has_passed(self):
        st = state(signal("SPY", True, BOTH))
        page = build.stance(st["signals"], REGIME, {}, st["latest_close"], {"usable": True}, entry_passed=True)
        self.assertEqual(page["status"], "registered_setup_entry_passed")
        self.assertIn("has passed", page["headline"])

    def test_new_records_carry_the_rule_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = stance_log.append_daily(Path(tmp), state(signal("SPY", True, CLOSE_ONLY)),
                                          pd.Timestamp("2026-11-12 18:00", tz=NY),
                                          entry_time=lambda s: pd.Timestamp("2026-11-13 09:30", tz=NY))
            self.assertEqual(out["logged"], 2)
            rows = calls.read(Path(tmp), stance_log.LOG)
            self.assertEqual({r["stance_rules"] for r in rows}, {2})
            self.assertEqual(rows[0]["direction"], "flat")


class ExportValidationTests(unittest.TestCase):
    GOOD = {"kind": "trade_simulation", "schema": 1, "strategies": [row("etf_next_open", "Lead")],
            "signal_days": {"SPY:rsi2_below_10": {"last_date": "2026-11-06", "dates": ["2026-11-02"]}}}

    def load(self, payload):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "export.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            return signals.load_export(path)

    def test_a_complete_export_loads(self):
        payload, info = self.load(self.GOOD)
        self.assertEqual(info["status"], "ok")
        self.assertEqual(len(payload["strategies"]), 1)

    def test_damaged_exports_are_invalid_instead_of_crashing(self):
        def without(path, key):
            payload = copy.deepcopy(self.GOOD)
            target = payload
            for part in path:
                target = target[part]
            target.pop(key)
            return payload
        damaged = [without([], "strategies"), without([], "signal_days"), without(["strategies", 0], "mode"),
                   without(["strategies", 0], "development"), without(["strategies", 0, "development"], "matched"),
                   without(["signal_days", "SPY:rsi2_below_10"], "last_date"), [1, 2], {**self.GOOD, "schema": 2}]
        for payload in damaged:
            got, info = self.load(payload)
            self.assertIsNone(got)
            self.assertEqual(info["status"], "invalid")


class OpsTests(unittest.TestCase):
    def test_empty_folder_reports_missing_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = ops.build(Path(tmp), pd.Timestamp("2026-11-13 18:00", tz=NY), "2026-11-13")
            self.assertEqual(out["status"], "missing")
            self.assertEqual([p for p in Path(tmp).rglob("*") if p.is_file()], [])

    def test_missed_sessions_are_listed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            log = root / "data" / "monitor" / "paper_events.jsonl"
            log.parent.mkdir(parents=True)
            log.write_text("".join(json.dumps({"type": "decision", "key": f"v1:{day}:rule"}) + "\n"
                                   for day in ("2026-11-06", "2026-11-12")), encoding="utf-8")
            out = ops.build(root, pd.Timestamp("2026-11-12 18:00", tz=NY), "2026-11-12")
            self.assertEqual(out["missed_decisions"], ["2026-11-09", "2026-11-10", "2026-11-11"])
            first = out["rows"][0]
            self.assertEqual((first["label"], first["state"], first["last"]), ("Paper decisions", "late", "2026-11-12"))


class JournalTests(unittest.TestCase):
    def test_notes_chain_keep_the_page_snapshot_and_look_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snap = lambda r: {"latest_close": "2026-11-03", "stance": "Flat"}  # noqa: E731
            first = journal.append(root, {"text": " VIX curve inverted ", "tags": "VIX, term-structure #vix"},
                                   pd.Timestamp("2026-11-03 22:00", tz="UTC"), snapshot=snap)
            self.assertEqual((first["text"], first["tags"], first["instrument"]), ("VIX curve inverted", ["vix", "term-structure"], None))
            journal.append(root, {"text": "QQQ gap", "instrument": "qqq"}, pd.Timestamp("2026-11-04 22:00", tz="UTC"), snapshot=None)
            days = pd.bdate_range("2026-11-02", periods=10)
            f = pd.DataFrame({"open": np.arange(100, 110, dtype=float), "close": np.arange(101, 111, dtype=float)}, index=days)
            out = journal.summary(root, {"SPY": f, "QQQ": f})
            self.assertEqual((out["count"], out["tags"]), (2, {"term-structure": 1, "vix": 1}))
            oldest = out["notes"][-1]
            self.assertEqual(oldest["snapshot"]["stance"], "Flat")
            self.assertEqual((oldest["look_back"]["symbol"], oldest["look_back"]["entry_date"]), ("SPY", "2026-11-04"))
            self.assertAlmostEqual(oldest["look_back"]["next_5"], 107 / 102 - 1)  # Nov 4 open to Nov 10 close
            self.assertIsNone(oldest["look_back"]["next_20"])
            self.assertEqual(out["notes"][0]["look_back"]["symbol"], "QQQ")
            path = root / journal.LOG
            path.write_text(path.read_text(encoding="utf-8").replace("inverted", "normal"), encoding="utf-8")
            self.assertEqual(journal.summary(root, {})["status"], "broken")

    def test_validation(self):
        for bad in ({"text": ""}, {"text": "x" * 2001}, {"text": "x", "instrument": "TSLA"}, {"text": "x", "tags": "bad tag!"},
                    {"text": "x", "tags": " ".join(f"t{i}" for i in range(9))}):
            with self.assertRaises(ValueError):
                journal.validate(bad)


class LedgerTests(unittest.TestCase):
    def test_ideas_move_through_stages_and_everything_tested_is_counted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            t = lambda day: pd.Timestamp(f"2026-11-{day:02d} 22:00", tz="UTC")  # noqa: E731
            a = ledger.create(root, {"title": "Gap split", "claim": "Big gaps use up the bounce", "from_note": "3"}, t(13))
            b = ledger.create(root, {"title": "Rally short", "claim": "Fade big up days", "stage": "backtested"}, t(13))
            self.assertEqual((a["idea"], b["idea"], a["from_note"]), (1, 2, 3))
            ledger.update(root, {"idea": 1, "stage": "registered"}, t(14))
            ledger.update(root, {"idea": 2, "stage": "dropped", "result": "Failed the 1993-2009 holdout"}, t(15))
            out = ledger.summary(root)
            first, second = out["ideas"]
            self.assertEqual((first["stage"], [h["stage"] for h in first["history"]]), ("registered", ["idea", "registered"]))
            self.assertEqual((second["stage"], second["result"], second["updated"]), ("dropped", "Failed the 1993-2009 holdout", "2026-11-15"))
            self.assertEqual((out["total"], out["tested"], out["dropped"], out["counts"]["registered"]), (2, 1, 1, 1))
            ledger.create(root, {"title": "Dropped after a test", "claim": "x", "stage": "dropped", "result": "No evidence"}, t(16))
            ledger.create(root, {"title": "Dropped untested", "claim": "x", "stage": "dropped"}, t(16))
            self.assertEqual(ledger.summary(root)["tested"], 2)  # a result makes a dropped idea count as tested
            for bad in ({"idea": 9, "stage": "kept"}, {"idea": 1}, {"idea": 1, "stage": "maybe"}):
                with self.assertRaises(ValueError):
                    ledger.update(root, bad)
            with self.assertRaises(ValueError):
                ledger.create(root, {"title": "No claim"})


class CallBasisTests(unittest.TestCase):
    def test_basis_tags_are_validated_and_summarised(self):
        good = {"instrument": "SPY", "direction": "long", "horizon_sessions": 2, "invalidation": "x"}
        self.assertEqual(calls.validate({**good, "basis": ["News", "signal"]})["basis"], ["signal", "news"])
        self.assertEqual(calls.validate(good)["basis"], [])
        with self.assertRaises(ValueError):
            calls.validate({**good, "basis": ["astrology"]})
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            calls.append(root, {**good, "basis": ["signal"]}, pd.Timestamp("2026-11-03 22:00", tz="UTC"))
            days = pd.bdate_range("2026-11-02", periods=10)
            f = pd.DataFrame({"open": np.arange(100, 110, dtype=float), "close": np.arange(101, 111, dtype=float)}, index=days)
            out = calls.summary(root, {"SPY": f})
            self.assertEqual([(b["basis"], b["scored"]) for b in out["by_basis"]], [("signal", 1)])


if __name__ == "__main__":
    unittest.main()
