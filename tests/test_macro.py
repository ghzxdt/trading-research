"""Macro tab: FRED series download and description, the VIX cross-check, and rendering macro.html."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from thesis import build, macro  # noqa: E402

NY = "America/New_York"


class Reply:
    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        pass


def csv(series, values, start="2024-01-01", freq="B"):
    days = pd.date_range(start, periods=len(values), freq=freq)
    return f"observation_date,{series}\n" + "\n".join(f"{d:%Y-%m-%d},{v}" for d, v in zip(days, values))


class MacroTests(unittest.TestCase):
    def test_refresh_rejects_implausible_series_and_keeps_the_saved_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            good = lambda url, **k: Reply(csv(url.split("=")[-1], [5.2 + i / 200 for i in range(60)]))  # noqa: E731  (inside every range)
            self.assertTrue(all(s["ok"] for s in macro.refresh(root, get=good).values()))
            bad = lambda url, **k: Reply(csv(url.split("=")[-1], [500.0] * 60))  # noqa: E731
            status = macro.refresh(root, get=bad)
            self.assertFalse(status["NFCI"]["ok"])
            saved = (root / macro.FOLDER / "NFCI.csv").read_text(encoding="utf-8")
            self.assertNotIn("500.0", saved)

    def test_describe_changes_and_percentile(self):
        s = pd.Series([1.0, 2.0, 3.0, 4.0], index=pd.to_datetime(["2026-07-01", "2026-08-01", "2026-09-01", "2026-10-01"]))
        out = macro.describe(s)
        self.assertEqual((out["value"], out["change_1m"], out["change_3m"], out["percentile"]), (4.0, 1.0, 3.0, 1.0))
        self.assertIsNone(macro.describe(pd.Series(dtype=float)))

    def test_vix_check(self):
        days = pd.bdate_range("2026-10-01", periods=10)
        cboe = pd.Series([20.0 + i for i in range(10)], index=days)
        fred = cboe.iloc[:-1].copy()
        same = macro.vix_check(cboe, fred)
        self.assertEqual((same["status"], same["compared"], same["fred_missing_latest"]), ("match", 9, [f"{days[-1]:%Y-%m-%d}"]))
        fred.iloc[3] += 0.5
        off = macro.vix_check(cboe, fred)
        self.assertEqual((off["status"], off["differences"]), ("differ", 1))

    def test_build_reads_the_target_range_and_the_sahm_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = root / macro.FOLDER
            folder.mkdir(parents=True)
            for series in macro.SERIES:
                value = {"DFEDTARL": 3.75, "DFEDTARU": 4.0, "SAHMREALTIME": 0.6, "VIXCLS": 18.0}.get(series, 1.0)
                (folder / f"{series}.csv").write_text(csv(series, [value] * 40), encoding="utf-8")
            out = macro.build(root, pd.Timestamp("2026-11-14 12:00", tz=NY))
            self.assertEqual((out["target_range"]["low"], out["target_range"]["high"], out["sahm_triggered"]), (3.75, 4.0, True))
            self.assertNotIn("VIXCLS", [r["series"] for r in out["rows"]])
            self.assertEqual(macro.build(root / "none", pd.Timestamp("2026-11-14 12:00", tz=NY))["status"], "unavailable")

    def test_macro_page_renders_with_the_thesis_styles_and_its_own_tab(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            state = {"schema_version": 2, "as_of": "2026-11-14T18:00:00-05:00", "stance": {"headline": "x"},
                     "evidence_source": {}, "macro": {"status": "ok", "rows": []}, "releases": {"status": "ok", "rows": []},
                     "first_release": {"status": "no_key"}, "regime": {"credit": [], "rates": {}}}
            build.render(out, out, state)
            page = (out / "macro.html").read_text(encoding="utf-8")
            self.assertNotIn("{{", page)
            self.assertIn('aria-current="page">Macro', page)
            self.assertIn("<style>", page)
            embedded = page.split('id="macro-state">')[1].split("</script>")[0]
            self.assertEqual(json.loads(embedded)["first_release"]["status"], "no_key")
            self.assertIn('href="macro.html"', (out / "thesis.html").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
