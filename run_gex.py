"""The GEX / DIX tab: reads your GEX/DIX copy plus what the other tabs already pulled, writes output/gex.html.

Usage:
    python run_gex.py                 # rebuild the tab from your saved copy
    python run_gex.py --import        # first copy in the newest DIX CSV from your Downloads folder
    python run_gex.py --import --downloads "D:/some/folder"   # look somewhere else
    python run_gex.py --open          # open the tab when done

The Update button on the tab does the same as --import (it needs hub_server.py running).
"""

from __future__ import annotations

import argparse
import sys
import warnings
import webbrowser
from datetime import datetime
from pathlib import Path

import pandas as pd

from gex import build, data, importer, report
from stage1.studies import Judge
from validation import FLOAT_FORMAT, output_dir, validate_daily_table, write_component_manifest

ROOT = Path(__file__).resolve().parent
OUT = output_dir(ROOT)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--import", dest="do_import", action="store_true", help="copy in the newest DIX CSV from Downloads first")
    ap.add_argument("--downloads", help="folder to look in instead of your Downloads folder")
    ap.add_argument("--open", action="store_true", help="open the tab when done")
    ap.add_argument("--offline", action="store_true", help="compatibility flag; this builder never downloads data")
    args = ap.parse_args()
    warnings.simplefilter("ignore", category=FutureWarning)

    if args.do_import:
        res = importer.import_latest(Path(args.downloads) if args.downloads else None)
        print(("  " + res["message"]) if res["ok"] else ("  Not imported: " + res["error"]))

    dix = data.load_dix()
    tp, lp = OUT / "daily_table.csv", OUT / "leverage_markets.csv"
    t = pd.read_csv(tp, parse_dates=["date"], index_col="date") if tp.exists() else None
    if t is not None:
        validate_daily_table(t)
    lev = pd.read_csv(lp) if lp.exists() else None
    lev_saved = datetime.fromtimestamp(lp.stat().st_mtime) if lp.exists() else None
    status = data.write_status(t, OUT)

    studies = []
    if dix is not None and t is not None:
        j = data.joined(t, dix)
        judge = Judge()
        studies = [build.study_reading(j, dix, lev), build.study_recent(dix), build.study_history(j, judge)]
        j.to_csv(OUT / "gex_daily.csv", float_format=FLOAT_FORMAT)
        tests = judge.tests_run
    else:
        tests = 0
    checks = build.health(dix, data.saved_at(), t, lev_saved, status)
    copy_through = f"{dix.index.max():%Y-%m-%d}" if dix is not None else None
    path = report.build(studies, checks, status, copy_through, t.index[-1] if t is not None else None, OUT / "gex.html")
    write_component_manifest("gex", OUT, {"copy_through": copy_through, "tests_run": tests, "status": status.get("state")})
    print(f"GEX / DIX tab: {status['label']}" + (f" ({tests} luck tests)" if tests else ""))
    print(f"  Page: {path}")
    if args.open:
        webbrowser.open(path.as_uri())


if __name__ == "__main__":
    sys.exit(main())
