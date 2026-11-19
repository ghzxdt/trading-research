"""Free share-liquidity pipeline: spread sampling and immutable day records in their own journal. (Options parts,
OCC volume included, were removed on 2026-11-19 with the user's trim list.)"""
import json, tempfile, unittest
from pathlib import Path

import pandas as pd

import liquidity_free as lf
import scheduled_collect as sc
from liquidity_screen import _load, evaluate
from validation import NY

ROOT = Path(__file__).resolve().parents[1]
SCRATCH = ROOT / "work" / "liquidity_free_tests"
SCRATCH.mkdir(parents=True, exist_ok=True)


def quote(symbol):return {"bid": 99.99, "ask": 100.01, "price": 100.0}


class SamplingTests(unittest.TestCase):
    def setUp(self):self.tmp = tempfile.TemporaryDirectory(dir=SCRATCH);self.root = Path(self.tmp.name)
    def tearDown(self):self.tmp.cleanup()

    def test_sample_measures_the_share_spread_only(self):
        row = lf.sample_symbol("SPY", pd.Timestamp("2026-11-09 10:30", tz=NY), quote)
        self.assertAlmostEqual(row["share_spread_bps"], 2.0, places=6)
        self.assertNotIn("option_median_spread_bps", row)  # no options data since 2026-11-19

    def test_sampling_only_in_regular_hours_on_trading_days(self):
        for when, expected in (("2026-11-09 10:30", 1), ("2026-11-09 09:35", 0), ("2026-11-09 16:30", 0), ("2026-11-26 12:30", 0)):
            result = lf.sample(self.root, ["SPY"], pd.Timestamp(when, tz=NY), quote)
            self.assertEqual(result["sampled"], expected, when)


class DayRecordTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=SCRATCH);self.root = Path(self.tmp.name);self.said = []
        for minute in ("10:30", "12:30", "14:30", "15:50"):
            lf.sample(self.root, ["SPY"], pd.Timestamp(f"2026-11-09 {minute}", tz=NY), quote)
    def tearDown(self):self.tmp.cleanup()

    def update(self, when):
        return lf.update(self.root, ["SPY"], pd.Timestamp(when, tz=NY),
                         volume_for=lambda s: {"2026-11-09": 80_000_000}, say=self.said.append)

    def test_complete_day_is_written_once_to_the_snapshot_journal_only(self):
        self.assertEqual(self.update("2026-11-09 20:10")["records"], 1)
        row = _load(self.root, "snapshot")[("SPY", "2026-11-09")]
        self.assertTrue(row["complete_session"])
        self.assertEqual((row["share_volume"], row["options_volume"]), (80_000_000, None))
        self.assertAlmostEqual(row["share_median_spread_bps"], 2.0, places=4)
        self.assertEqual(row["provenance"]["share_samples"], 4)
        self.assertEqual(_load(self.root, "verified"), {})  # the strict journal is untouched
        self.assertEqual(self.update("2026-11-09 21:10")["records"], 0)  # immutable: not rewritten

    def test_snapshot_journal_feeds_the_shares_gate(self):
        self.update("2026-11-09 20:10")
        policy = {"min_share_volume": 1, "max_share_spread_bps": 10}
        snap = evaluate(self.root, "SPY", ["2026-11-10"], policy, "2026-11-10T14:00:00+00:00", "shares", journal="snapshot")
        strict = evaluate(self.root, "SPY", ["2026-11-10"], policy, "2026-11-10T14:00:00+00:00", "shares")
        self.assertEqual((snap["journal"], strict["journal"]), ("snapshot", "verified"))
        self.assertFalse(snap["research_eligible"])  # one sampled day, not twenty


class SlotTests(unittest.TestCase):
    def test_slots(self):
        cases = {"2026-11-09 10:30": "sample", "2026-11-09 14:30": "sample", "2026-11-09 15:50": "preclose",
                 "2026-11-09 20:10": "bars", "2026-11-09 09:00": "bars", "2026-11-26 12:30": "bars"}
        for when, slot in cases.items():
            self.assertEqual(sc.slot_for(pd.Timestamp(when, tz=NY)), slot, when)

    def test_each_slot_runs_its_steps(self):
        for when, expected in (("2026-11-09 10:00", []), ("2026-11-09 10:30", ["sample"]),
                               ("2026-11-09 15:50", ["collect", "sample"]),
                               ("2026-11-09 20:10", ["collect", "liquidity", "backup"])):
            calls = []
            sc.run(Path("."), now=lambda w=when: pd.Timestamp(w, tz=NY), symbols=["SPY"], say=lambda m: None,
                   lock_state=lambda r: {"busy": False},
                   collect=lambda root, symbols, include_options: calls.append("collect") or {"results": [{"symbol": "SPY", "bar_status": "collected"}]},
                   sample=lambda root, symbols, now: calls.append("sample") or {"sampled": 1},
                   liquidity=lambda root, symbols, say: calls.append("liquidity"),
                   backup=lambda root, say: calls.append("backup"))
            self.assertEqual(calls, expected, when)


if __name__ == "__main__":
    unittest.main()
