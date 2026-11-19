"""Review C13 (2026-11-18): the shares baseline (experiment A) is gated on share liquidity, not options data."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import run_intraday  # noqa: E402

BLOCKED = {"research_eligible": False, "reasons": ["blocked for the test"], "session_results": [], "thresholds": {}}
BAR = {"symbol": "SPY", "timestamp": "2026-11-17T14:30:00+00:00"}


class SharesGateTests(unittest.TestCase):
    def test_research_and_paper_use_the_shares_gate(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict("os.environ", {"APP_REPLAY": "0", "APP_OFFLINE": "0"}), \
                patch("intraday.store.load_bars", return_value=[BAR]), \
                patch("liquidity_screen.evaluate", return_value=BLOCKED) as gate:
            with self.assertRaises(ValueError):
                run_intraday.research(Path(tmp), "SPY")
            self.assertEqual(gate.call_args.kwargs["execution"], "shares")
            with self.assertRaises(ValueError):
                run_intraday.research(Path(tmp), "SPY", execution="options")
            self.assertEqual(gate.call_args.kwargs["execution"], "options")
        snapshot = {"quality": {"reasons": [], "forward_eligible": True}}
        with tempfile.TemporaryDirectory() as tmp, patch("intraday.store.load_bars", return_value=[]), \
                patch("intraday.features.snapshot", return_value=snapshot), \
                patch("liquidity_screen.evaluate", return_value={**BLOCKED, "window_sessions": 20, "required_fraction": 0.8}) as gate, \
                patch("intraday.paper.record_decision", return_value={"recorded": False}) as record:
            run_intraday.paper_observation(Path(tmp), "SPY")
            self.assertEqual(gate.call_args.kwargs["execution"], "shares")
            self.assertEqual(record.call_args.kwargs["qualification_policy"]["execution"], "shares")


if __name__ == "__main__":
    unittest.main()
