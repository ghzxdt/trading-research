"""Review B8 (2026-11-18): idea ledger schema 2 with structured fields; old events stay valid; a registered
idea's testable fields are fixed."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from thesis import calls, ledger  # noqa: E402

T = lambda day: pd.Timestamp(f"2026-11-{day:02d} 22:00", tz="UTC")  # noqa: E731


class LedgerSpecTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_structured_fields_old_events_and_the_frozen_rule(self):
        # An old schema 1 event, written the way the ledger wrote them before 2026-11-18.
        body = {"schema": 1, "id": 1, "recorded_utc": "2026-11-13T22:00:00+00:00", "recorded_et": "2026-11-13T17:00:00-05:00",
                "type": "create", "idea": 1, "title": "Old idea", "claim": "x", "test": "", "route": "", "stage": "registered",
                "result": "", "evidence_ref": "", "previous_hash": ""}
        path = self.root / ledger.LOG
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({**body, "hash": calls._digest(body)}) + "\n", encoding="utf-8")
        new = ledger.create(self.root, {"title": "Gap fade", "claim": "Large gaps fill", "rule": "SPY gap below -1% at 9:30",
                                        "decision_time": "9:30 AM ET", "horizon": "same session", "benchmark": "buy at the open",
                                        "expected_result": "fills 60% of the time", "invalidate": "fills under 50% in 40 days",
                                        "monitor": "VIX"}, T(18))
        self.assertEqual((new["schema"], new["idea"], new["spec"]["rule"]), (2, 2, "SPY gap below -1% at 9:30"))
        ideas = {i["idea"]: i for i in ledger.summary(self.root)["ideas"]}
        self.assertEqual((ideas[1]["spec"], ideas[1]["missing"][0]), ({}, "rule"))  # old event: still valid, no spec
        self.assertEqual(ideas[2]["missing"], [])
        ledger.update(self.root, {"idea": 1, "rule": "QQQ RSI(14) below 30, buy next open"}, T(18))  # filling a gap is fine
        ledger.update(self.root, {"idea": 2, "stage": "registered"}, T(19))
        with self.assertRaises(ValueError):  # registered: the rule can't change
            ledger.update(self.root, {"idea": 2, "rule": "SPY gap below -2%"}, T(20))
        ledger.update(self.root, {"idea": 2, "monitor": "VIX and VIX3M"}, T(20))  # not a testable field
        ideas = {i["idea"]: i for i in ledger.summary(self.root)["ideas"]}
        self.assertEqual(ideas[1]["spec"]["rule"], "QQQ RSI(14) below 30, buy next open")
        self.assertEqual((ideas[2]["spec"]["rule"], ideas[2]["spec"]["monitor"]), ("SPY gap below -1% at 9:30", "VIX and VIX3M"))
        with self.assertRaises(ValueError):
            ledger.create(self.root, {"title": "t", "claim": "c", "rule": "x" * 601})


if __name__ == "__main__":
    unittest.main()
