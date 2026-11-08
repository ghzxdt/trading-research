"""Weekday intraday collection, run by the Windows scheduled task "Trading Research Intraday Collection".

Yahoo serves only the last few days of one-minute bars, so any day nobody collects is lost for good.
This runs the app's own collector (intraday_collect.collect) for every active Today instrument:

- 3:50 PM ET ("options" run): minute bars plus each instrument's current option chains, while the
  market is open and Yahoo's option bid/ask are live. Chains are still indicative, not executable.
- 8:10 PM ET ("bars" run): minute bars only, after the extended session ends, so each day's archive
  is complete. A late start (computer was off) also runs bars only; the five-day archive forgives it.

It waits for a running build (an offline rebuild refuses to publish if data/ changes underneath it)
and for a collection started from the Today page. It never records paper decisions or trades.
Log: work/intraday_collect.log. Exit codes: 0 collected; 1 partly failed; 2 nothing collected;
3 unexpected error.
"""
from __future__ import annotations

import argparse
import json
import time
import traceback
from pathlib import Path

import pandas as pd

from app_control import build_lock_state
from validation import NY, equity_sessions

ROOT = Path(__file__).resolve().parent
LOG_PATH = ROOT / "work" / "intraday_collect.log"
STATUS = Path("data/terminal/collection_status.json")
STALE_RUNNING = pd.Timedelta(minutes=30)  # a "running" status older than this was interrupted


def log(message: str) -> None:
    line = f"[{pd.Timestamp.now(tz=NY):%Y-%m-%d %H:%M:%S} ET] {message}"
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as stream:
        stream.write(line + "\n")
    print(line, flush=True)  # no-op under pythonw


def wants_options(now: pd.Timestamp) -> bool:
    """Option chains only on a trading day between 3:30 and 4:00 PM ET, when quotes are live."""
    t = now.tz_convert(NY)
    day = t.tz_localize(None).normalize()
    trading_day = len(equity_sessions(day, day)) == 1
    return trading_day and (15 * 60 + 30) <= t.hour * 60 + t.minute < 16 * 60


def collection_running(root: Path, now: pd.Timestamp) -> bool:
    """True while another process (e.g. the Today page's button) is mid-collection."""
    try:
        status = json.loads((Path(root) / STATUS).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    started = pd.Timestamp(status.get("started_at")) if status.get("started_at") else None
    return bool(status.get("running")) and started is not None and now - started.tz_convert(NY) < STALE_RUNNING


def summarize(status: dict) -> tuple[int, str]:
    results = status.get("results") or []
    bars_ok = [r["symbol"] for r in results if r.get("bar_status") == "collected"]
    bars_bad = [r["symbol"] for r in results if r.get("bar_status") != "collected"]
    options = [r for r in results if "options_status" in r]
    options_ok = sum(1 for r in options if r["options_status"] == "indicative_only")
    contracts = sum(r.get("option_contracts", 0) for r in options)
    text = f"Bars collected for {len(bars_ok)} of {len(results)} instruments"
    if bars_bad:
        text += f" (not collected: {', '.join(bars_bad)})"
    if options:
        failed = [r["symbol"] for r in options if r["options_status"] != "indicative_only"]
        text += f"; option chains for {options_ok} of {len(options)} ({contracts:,} contracts)"
        if failed:
            text += f", failed: {', '.join(failed)}"
    code = 2 if not bars_ok else 1 if bars_bad or (options and options_ok < len(options)) else 0
    return code, text + "."


def run(root: Path = ROOT, *, now=lambda: pd.Timestamp.now(tz=NY), collect=None, symbols=None,
        sleep=time.sleep, say=log, lock_state=build_lock_state, wait_limit: int = 900) -> int:
    if collect is None:
        from intraday_collect import collect
    if symbols is None:
        from terminal_config import active_symbols
        symbols = active_symbols(root)
    waited = 0
    while lock_state(root)["busy"] or collection_running(root, now()):
        if waited >= wait_limit:
            say(f"Gave up after {waited // 60} minutes waiting for a build or another collection; nothing collected.")
            return 2
        sleep(15)
        waited += 15
    options = wants_options(now())
    say(f"Collecting {'minute bars and option chains' if options else 'minute bars'} for {len(symbols)} instruments"
        + (f" (waited {waited}s)." if waited else "."))
    status = collect(root, symbols, include_options=options)
    code, text = summarize(status)
    say(text)
    return code


def main(argv=None) -> int:
    argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter).parse_args(argv)
    try:
        return run(ROOT)
    except Exception:
        log("Collection failed:\n" + traceback.format_exc())
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
