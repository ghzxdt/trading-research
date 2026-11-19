"""Review B6 (2026-11-18, user: "Yes, go ahead"): one opportunity id across the stance log, paper book, calls and
journal notes; abstentions, vetoes and missed closes recorded as such; older records untouched."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from thesis import calls, journal, opportunity, paper_book, stance_log  # noqa: E402

NY = "America/New_York"
SHA = "793a58bd49ec0000"


def evidence(open_verdict, close_verdict="Lead"):
    rows = [{"mode": "etf_next_open", "verdict": open_verdict, "exit": "hold_5"},
            {"mode": "etf_close", "verdict": close_verdict, "exit": "hold_5"}]
    return [{**r, "development": {"trades": 1}, "holdout": None} for r in rows]


def state(latest, qqq_open="Lead", spy_fired=False):
    sig = [{"symbol": "QQQ", "signal": "bollinger_lower_close", "fired": True, "evidence": evidence(qqq_open),
            "crosscheck": {"status": "match", "checked_through": latest}},
           {"symbol": "SPY", "signal": "rsi2_below_10", "fired": spy_fired, "evidence": evidence("No edge"),
            "crosscheck": {"status": "match", "checked_through": latest}}]
    return {"latest_close": latest, "evidence_source": {"status": "ok", "sha256": SHA}, "signals": sig, "stance": {}}


def evening(day):
    return pd.Timestamp(f"{day} 21:00", tz=NY)


def entry(day):
    return (pd.Timestamp(day) + pd.offsets.BDay(1)).tz_localize(NY) + pd.Timedelta(hours=9, minutes=30)


class OpportunityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_stance_records_carry_dispositions_and_missed_closes_are_recorded(self):
        stance_log.append_daily(self.root, state("2026-11-12"), evening("2026-11-12"), entry)
        out = stance_log.append_daily(self.root, state("2026-11-17", qqq_open="No edge", spy_fired=True),
                                      evening("2026-11-17"), entry)
        self.assertEqual((out["logged"], out["missed"]), (2, 4))  # Nov 13 and 16, SPY and QQQ
        rows = calls.read(self.root, stance_log.LOG)
        qqq = [r for r in rows if r["instrument"] == "QQQ"]
        self.assertEqual(qqq[0]["opportunities"], [{"id": "2026-11-12:QQQ:bollinger_lower_close:next_open:793a58bd49ec",
                                                    "rule": "bollinger_lower_close", "policy": "next_open", "disposition": "long"}])
        self.assertEqual([r["latest_close"] for r in qqq[1:3]], ["2026-11-13", "2026-11-16"])
        self.assertTrue(all(r["direction"] == "missed" and r["recorded_after_entry"] for r in qqq[1:3]))
        self.assertEqual(qqq[3]["opportunities"][0]["disposition"], "abstain: closing-price Lead only")
        spy = [r for r in rows if r["instrument"] == "SPY" and r["latest_close"] == "2026-11-17"][0]
        self.assertEqual(spy["opportunities"][0]["disposition"], "abstain: closing-price Lead only")
        again = stance_log.append_daily(self.root, state("2026-11-17"), evening("2026-11-17"), entry)
        self.assertEqual((again["logged"], again["missed"]), (0, 0))
        summary = stance_log.summary(self.root, {})
        self.assertEqual(summary["missed_closes"], ["2026-11-13", "2026-11-16"])
        self.assertEqual(summary["scoreboard"]["calls"], 4)  # missed records are not scored

    def test_calls_take_veto_override_and_notes_link(self):
        stance_log.append_daily(self.root, state("2026-11-12"), evening("2026-11-12"), entry)
        rows = calls.read(self.root, stance_log.LOG)
        page_long_id = "2026-11-12:QQQ:bollinger_lower_close:next_open:793a58bd49ec"
        call = lambda instrument, direction, close="2026-11-12": {  # noqa: E731
            "instrument": instrument, "direction": direction, "context": {"latest_close": close}}
        self.assertEqual(opportunity.link_call(rows, call("QQQ", "long")), {"opportunity_ids": [page_long_id], "relation": "take"})
        self.assertEqual(opportunity.link_call(rows, call("TQQQ", "long"))["relation"], "take")
        self.assertEqual(opportunity.link_call(rows, call("SQQQ", "long"))["relation"], "veto")  # an inverse ETF: short QQQ
        self.assertEqual(opportunity.link_call(rows, call("QQQ", "flat"))["relation"], "veto")
        self.assertEqual(opportunity.link_call(rows, call("SPY", "flat"))["relation"], "agree flat")
        self.assertEqual(opportunity.link_call(rows, call("IWM", "long"))["relation"], "own view")
        self.assertEqual(opportunity.link_call(rows, call("QQQ", "long", "2026-11-18"))["relation"], "unlinked")
        stance_log.append_daily(self.root, state("2026-11-13", qqq_open="No edge"), evening("2026-11-13"), entry)
        rows = calls.read(self.root, stance_log.LOG)
        self.assertEqual(opportunity.link_call(rows, call("QQQ", "long", "2026-11-13"))["relation"], "override")
        saved = calls.append(self.root, {"instrument": "QQQ", "direction": "long", "horizon_sessions": 5, "invalidation": "x",
                                         "context": {"latest_close": "2026-11-12"}}, pd.Timestamp("2026-11-13 02:00", tz="UTC"))
        self.assertEqual((saved["relation"], saved["opportunity_ids"]), ("take", [page_long_id]))
        note = journal.append(self.root, {"text": "QQQ under the band", "instrument": "TQQQ"},
                              pd.Timestamp("2026-11-13 02:00", tz="UTC"), snapshot=lambda r: {"latest_close": "2026-11-12"})
        self.assertEqual(note["opportunity_ids"], [page_long_id])

    def test_the_paper_book_trade_shares_the_stance_records_id(self):
        stance_log.append_daily(self.root, state("2026-11-12"), evening("2026-11-12"), entry)
        record = [r for r in calls.read(self.root, stance_log.LOG) if r["direction"] == "long"][0]
        days = pd.bdate_range("2026-11-10", periods=12)
        frame = pd.DataFrame({"open": 100.0, "close": 100.0}, index=days)
        [trade] = paper_book.trades([record], {"QQQ": frame}, [])
        self.assertEqual(trade["opportunity_id"], record["opportunities"][0]["id"])

    def test_older_records_derive_the_same_ids_without_being_changed(self):
        old = {"latest_close": "2026-11-06", "instrument": "QQQ", "rules": ["bollinger_lower_close"],
               "close_only_rules": [], "evidence_sha256": SHA, "direction": "long"}
        self.assertEqual(opportunity.of_record(old)[0]["id"], "2026-11-06:QQQ:bollinger_lower_close:next_open:793a58bd49ec")


if __name__ == "__main__":
    unittest.main()
