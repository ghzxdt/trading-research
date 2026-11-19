"""GEX / DIX tab checks (moved from test_risk.py on 2026-11-19, when the Kalshi/perp tests there were removed with
the Leverage tab)."""
import os
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from gex import build as gex_build, data as gex_data


class GexTests(unittest.TestCase):
    def frame(self):
        j = pd.DataFrame(index=pd.bdate_range("2026-11-02", periods=4))
        j["gex_known"] = -1.
        j["expected_move"] = .01
        j["vix"] = 20.
        j["spy_daytime_vs_expected"] = 1.
        for proxy, day, high, low in [("spy", .01, 101., 90.), ("qqq", .02, 110., 99.)]:
            j[proxy + "_open"] = 100.
            j[proxy + "_high"] = high
            j[proxy + "_low"] = low
            j[proxy + "_daytime"] = day
        return j

    def test_stale_current_conditionals_are_suppressed(self):
        j = self.frame()
        dix = pd.DataFrame({"gex": [-1.], "dix": [.4]}, index=j.index[-1:])
        with patch.dict(os.environ, {"APP_AS_OF": "2026-12-01T10:00:00-05:00"}):
            study = gex_build.study_reading(j, dix)
        self.assertFalse(study["current_usable"])
        self.assertEqual(study["tables"], [])
        self.assertFalse(any("current VIX" in x["label"] for x in study["tiles"]))

    def test_rank_and_known_columns_do_not_use_future_data(self):
        dates = pd.bdate_range("2024-01-02", periods=300)
        dix = pd.DataFrame({"gex": np.arange(300), "dix": np.linspace(.3, .5, 300)}, index=dates)
        full = gex_data.joined(pd.DataFrame(index=dates), dix)
        part = gex_data.joined(pd.DataFrame(index=dates[:250]), dix.iloc[:250])
        pd.testing.assert_frame_equal(part, full.iloc[:250])
        self.assertTrue(np.isnan(gex_data.dix_rank(dix.dix).iloc[198]))
        self.assertEqual(gex_data.dix_rank(dix.dix).iloc[199], 1.)


if __name__ == "__main__":
    unittest.main()
