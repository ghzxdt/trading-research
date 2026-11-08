"""The Tickers tab: one page per ETF (stats, charts, order-flow stand-ins, news) plus an overview.

Usage:
    python run_tickers.py            # fetch fresh headlines, rebuild the pages
    python run_tickers.py --offline  # reuse the last saved headlines
    python run_tickers.py --open     # open the overview when done

Reads the Indexes tab's daily table (run run_stage1.py first), and, if present, the Leverage tab's
market table and your GEX/DIX file. It never changes them.
"""

from __future__ import annotations

import argparse
import sys
import warnings
import webbrowser
from datetime import datetime
from pathlib import Path

import pandas as pd

from tickers import build, news, report
from validation import freshness, output_dir, validate_daily_table, write_component_manifest

ROOT = Path(__file__).resolve().parent
OUT = output_dir(ROOT)


def _when(dt) -> str:
    return f"{dt:%b} {dt.day}, {dt:%I:%M %p}".replace(" 0", " ") if dt else "never"


def health(t: pd.DataFrame, nw: dict, lev, dix) -> dict:
    items = []

    def add(level, name, result, action=""):
        items.append({"level": level, "check": name, "result": result, "action": action})

    f = freshness(t.index[-1])
    add("ok" if f["ok"] else "warn", "Prices", f["reason"] + f" {len(t):,} trading days.", "Read-only; historical charts are not a current call.")
    st = nw["status"]
    yahoo = {k.split(": ")[1]: v for k, v in st.items() if k.startswith("Yahoo")}
    failed = [k for k, v in yahoo.items() if v["how"] in ("failed", "missing")]
    counts = ", ".join(f"{k} {len(nw['tickers'].get(k, []))}" for k in yahoo)
    newest = min((v["saved"] for v in yahoo.values() if v["saved"]), default=None)
    add("note" if failed else "ok", "Yahoo headlines", f"Headlines per ticker: {counts}. Saved {_when(newest)}." + (f" Not refreshed: {', '.join(failed)}." if failed else ""),
        "Headlines and links only. Unofficial source (same as the prices).")
    fed = st.get("Federal Reserve press releases", {})
    add("ok" if fed.get("how") in ("downloaded", "offline") else "note", "Fed press releases", f"{len(nw['fed'])} releases, saved {_when(fed.get('saved'))}.",
        "The Federal Reserve's official RSS feed.")
    add("ok" if lev is not None else "note", "Leverage tab data", "Found (Kalshi perps for the related-markets rows)." if lev is not None else "Not found; run run_leverage.py.")
    add("ok" if dix is not None else "note", "GEX/DIX file", f"Found, through {build._day(dix.index.max())} (shown on the SPY page)." if dix is not None else "Not found (optional).")
    add("note", "Order flow", "Daily stand-ins only (volume, close in range, A/D line).", "Trade-by-trade flow isn't free for these ETFs; minute data comes in stage 2.")
    summary = {lvl: sum(1 for i in items if i["level"] == lvl) for lvl in ("ok", "note", "warn")}
    return {"items": items, "banner": [i["result"] for i in items if i["level"] == "warn"], "summary": summary}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--offline", action="store_true", help="reuse the last saved headlines")
    ap.add_argument("--open", action="store_true", help="open the overview when done")
    args = ap.parse_args()
    warnings.simplefilter("ignore", category=FutureWarning)

    tp = OUT / "daily_table.csv"
    if not tp.exists():
        print("No Indexes-tab data yet: run run_stage1.py first.")
        sys.exit(1)
    t = pd.read_csv(tp, parse_dates=["date"], index_col="date")
    validate_daily_table(t)
    lp = OUT / "leverage_markets.csv"
    lev = pd.read_csv(lp) if lp.exists() else None
    try:
        from gex import data as gex_data
        dix = gex_data.load_dix()
    except Exception:
        dix = None
    events = pd.read_csv(ROOT / "data" / "events" / "events.csv", parse_dates=["date"])

    tks = [tk for _, group in build.CATEGORIES for tk in group]
    print("Fetching headlines (Yahoo, Federal Reserve)..." if not args.offline else "Loading saved headlines...")
    nw = news.fetch(tks, offline=args.offline)
    cal = news.calendar(events, t.index[-1])
    checks = health(t, nw, lev, dix)

    snaps = {}
    for tk in tks:
        if f"{tk.lower()}_close" not in t:
            continue
        studies, snap = build.ticker_page_studies(tk, t, lev, dix)
        snaps[tk] = snap
        report.build_ticker(tk, studies, nw, cal, checks, snap["date"], OUT)
    path = report.build_overview(snaps, nw, cal, checks, OUT)
    write_component_manifest("tickers", OUT, {"offline": args.offline, "market_through": str(t.index[-1].date()), "tickers": sorted(snaps)})
    print(f"Tickers tab: {len(snaps)} ticker pages + overview, {sum(len(v) for v in nw['tickers'].values())} headlines, {len(nw['fed'])} Fed releases.")
    print(f"  Overview: {path}")
    if args.open:
        webbrowser.open(path.as_uri())


if __name__ == "__main__":
    main()
