"""The Leverage tab: download Kalshi perps data, build the market table and studies, write the page.

Usage:
    python run_leverage.py            # download fresh Kalshi data, then build output/leverage.html
    python run_leverage.py --offline  # reuse the last download
    python run_leverage.py --open     # also open the page when done

Run run_stage1.py at least once first: the liquidation estimates use its SPY/QQQ history.
"""

from __future__ import annotations

import argparse
import warnings
import webbrowser
from pathlib import Path

import pandas as pd

from leverage import build, kalshi, report
from validation import FLOAT_FORMAT, freshness, output_dir, validate_daily_table, write_component_manifest

ROOT = Path(__file__).resolve().parent
OUT = output_dir(ROOT)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--offline", action="store_true", help="use the saved Kalshi data instead of downloading")
    ap.add_argument("--open", action="store_true", help="open the page in your browser when done")
    args = ap.parse_args()
    warnings.simplefilter("ignore", category=FutureWarning)

    raw = kalshi.fetch_all(offline=args.offline)
    table_path, long_path = OUT / "daily_table.csv", OUT / "long_history.csv"
    t = pd.read_csv(table_path, parse_dates=["date"], index_col="date") if table_path.exists() else None
    if t is not None:
        validate_daily_table(t)
    # Liquidation odds use the longest history available (SPY from 1993, QQQ from 1999), so crashes
    # like 2008 count; the other studies line up with the 2010-on daily table.
    t_long = pd.read_csv(long_path, parse_dates=["date"], index_col="date") if long_path.exists() else t
    if t is None:
        print("  No Indexes-tab data yet (run run_stage1.py first); liquidation history will be skipped.")

    print("Building the market table and studies...")
    rows = build.market_rows(raw)
    studies = [
        build.study_liquidation(rows, t_long),
        build.study_funding(rows, raw["funding"], t),
        build.study_tracking(rows, raw["funding"], t),
        build.study_overnight(rows, raw["hourly"], t),
    ]
    checks = build.health(raw, rows)
    OUT.mkdir(exist_ok=True)
    rows.to_csv(OUT / "leverage_markets.csv", index=False, float_format=FLOAT_FORMAT)
    path = report.build(rows, studies, checks, raw["fetched_utc"], OUT / "leverage.html")
    write_component_manifest("leverage", OUT, {"offline": args.offline, "snapshot_freshness": freshness(raw.get("fetched_utc"), kind="snapshot"), "markets": len(rows)})

    sm = checks["summary"]
    active = int((rows["status"] == "active").sum())
    print()
    print(f"Done. {len(rows)} perps on Kalshi ({active} active).")
    print(f"  Data check:   {sm['warn']} warning(s), {sm['note']} note(s), {sm['ok']} OK")
    print(f"  Page:         {path}")
    print(f"  Market table: {OUT / 'leverage_markets.csv'}")
    if args.open:
        webbrowser.open(path.as_uri())


if __name__ == "__main__":
    main()
