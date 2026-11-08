"""Free liquidity pipeline: spread sampling, OCC volume parsing, immutable day records in their own journal."""
import json, tempfile, unittest
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

import liquidity_free as lf
import scheduled_collect as sc
from liquidity_screen import _load, evaluate
from validation import NY

ROOT = Path(__file__).resolve().parents[1]
SCRATCH = ROOT / "work" / "liquidity_free_tests"
SCRATCH.mkdir(parents=True, exist_ok=True)
OCC_CSV = ("quantity,underlying,symbol,actype,porc,exchange,actdate\n"
           "1000,SPY,SPY,C,C,CBOE,11/06/2026,\n3000,SPY,SPY,M,P,AMEX,11/06/2026,\n500,SPY,2SPY,C,C,CBOE,11/06/2026,\n")


def quote(symbol):return {"bid": 99.99, "ask": 100.01, "price": 100.0}


def chain(symbol, spot):
    return [{"bid": 1.00, "ask": 1.02}, {"bid": 2.00, "ask": 2.02}, {"bid": 0, "ask": 0.05}, {"bid": 1.0, "ask": 1.1}]


class SamplingTests(unittest.TestCase):
    def setUp(self):self.tmp = tempfile.TemporaryDirectory(dir=SCRATCH);self.root = Path(self.tmp.name)
    def tearDown(self):self.tmp.cleanup()

    def test_sample_measures_share_and_option_spreads(self):
        row = lf.sample_symbol("SPY", pd.Timestamp("2026-11-09 10:30", tz=NY), quote, chain)
        self.assertAlmostEqual(row["share_spread_bps"], 2.0, places=6)
        self.assertEqual(row["option_contracts"], 3)  # the zero-bid contract is not a two-sided quote
        self.assertAlmostEqual(row["option_median_spread_bps"], 0.02 / 1.01 * 1e4, places=4)

    def test_sampling_only_in_regular_hours_on_trading_days(self):
        for when, expected in (("2026-11-09 10:30", 1), ("2026-11-09 09:35", 0), ("2026-11-09 16:30", 0), ("2026-11-26 12:30", 0)):
            result = lf.sample(self.root, ["SPY"], pd.Timestamp(when, tz=NY), quote, chain)
            self.assertEqual(result["sampled"], expected, when)

    def test_occ_counts_standard_contracts_and_halves_both_sides(self):
        self.assertEqual(lf.parse_occ(OCC_CSV, "SPY"),
                         {"all_series_sides": 4500, "standard_sides": 4000, "one_sided_estimate": 2000})
        self.assertIsNone(lf.parse_occ("quantity,underlying,symbol,actype,porc,exchange,actdate\n", "SPY"))


class DayRecordTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=SCRATCH);self.root = Path(self.tmp.name);self.said = []
        for minute in ("10:30", "12:30", "14:30", "15:50"):
            lf.sample(self.root, ["SPY"], pd.Timestamp(f"2026-11-09 {minute}", tz=NY), quote, chain)
    def tearDown(self):self.tmp.cleanup()

    def get(self, url, headers=None, timeout=None):
        text = OCC_CSV if "reportDate=20261109" in url else "quantity,underlying,symbol,actype,porc,exchange,actdate\n"
        return SimpleNamespace(text=text, raise_for_status=lambda: None)

    def update(self, when, get=None):
        return lf.update(self.root, ["SPY"], pd.Timestamp(when, tz=NY), get=get or self.get,
                         volume_for=lambda s: {"2026-11-09": 80_000_000}, say=self.said.append, pause=0)

    def test_complete_day_is_written_once_to_the_snapshot_journal_only(self):
        self.assertEqual(self.update("2026-11-09 20:10")["records"], 1)
        row = _load(self.root, "snapshot")[("SPY", "2026-11-09")]
        self.assertTrue(row["complete_session"])
        self.assertEqual((row["share_volume"], row["options_volume"]), (80_000_000, 2000))
        self.assertAlmostEqual(row["share_median_spread_bps"], 2.0, places=4)
        self.assertEqual(row["provenance"]["share_samples"], 4)
        self.assertEqual(_load(self.root, "verified"), {})  # the strict journal is untouched
        self.assertEqual(self.update("2026-11-09 21:10")["records"], 0)  # immutable: not rewritten

    def test_waits_for_occ_then_writes_without_it_after_three_sessions(self):
        empty = lambda url, headers=None, timeout=None: SimpleNamespace(
            text="quantity,underlying,symbol,actype,porc,exchange,actdate\n", raise_for_status=lambda: None)
        self.assertEqual(self.update("2026-11-09 20:10", empty)["waiting_for_occ"], 1)
        self.assertEqual(self.update("2026-11-12 20:10", empty)["records"], 1)
        self.assertIsNone(_load(self.root, "snapshot")[("SPY", "2026-11-09")]["options_volume"])

    def test_snapshot_journal_feeds_its_own_evaluation(self):
        self.update("2026-11-09 20:10")
        policy = {"min_share_volume": 1, "max_share_spread_bps": 10, "min_options_volume": 1, "max_options_spread_bps": 100}
        snap = evaluate(self.root, "SPY", ["2026-11-10"], policy, "2026-11-10T14:00:00+00:00", "options", journal="snapshot")
        strict = evaluate(self.root, "SPY", ["2026-11-10"], policy, "2026-11-10T14:00:00+00:00", "options")
        self.assertEqual((snap["journal"], strict["journal"]), ("snapshot", "verified"))
        self.assertFalse(snap["research_eligible"])  # one sampled day, not twenty


class SlotTests(unittest.TestCase):
    def test_slots(self):
        cases = {"2026-11-09 10:30": "sample", "2026-11-09 14:30": "sample", "2026-11-09 15:50": "options",
                 "2026-11-09 20:10": "bars", "2026-11-09 09:00": "bars", "2026-11-26 12:30": "bars"}
        for when, slot in cases.items():
            self.assertEqual(sc.slot_for(pd.Timestamp(when, tz=NY)), slot, when)

    def test_each_slot_runs_its_steps(self):
        for when, expected in (("2026-11-09 10:30", ["sample"]), ("2026-11-09 15:50", ["collect", "sample"]),
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
