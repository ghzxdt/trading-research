"""Twice-daily market snapshots: right after the stock close and before the open.

The scheduled task "Trading Research Market Snapshots" runs this on weekdays at 8:00 AM and
3:05 PM Central (9:00 AM and 4:05 PM ET). It saves what no source keeps for later:

  data/futures/futures_quotes.csv    S&P 500 and Nasdaq-100 E-mini futures from Yahoo (CME quotes,
                                     delayed): last price and time, the last price before 4:00 PM ET
                                     of the latest session, and the change since then
  data/macro/inflation_nowcast.csv   (4:05 PM run only) the Cleveland Fed's daily nowcasts of
                                     monthly CPI, core CPI, PCE and core PCE, plus actuals once out

and archives Yahoo headlines for SPY, QQQ and IWM plus Fed releases. Kalshi perps and macro markets were
collected here until 2026-11-19, when the user dropped all Kalshi and perpetual tracking ("no more tracking
that"); their files were moved to archive/kalshi-2026-11-19/.

Public data only: no accounts, no keys. Each source fails on its own without stopping the others. Rows are
only appended, after any running build finishes (an offline rebuild refuses to publish if its inputs change).
The evening task's git backup commits both files. Log: work/market_snapshot.log.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import re
import time
import traceback
from datetime import datetime, time as wall_clock, timedelta
from pathlib import Path

import pandas as pd
import requests

from app_control import build_lock_state
from validation import NY, equity_sessions

ROOT = Path(__file__).resolve().parent
FUTURES_FILE = Path("data/futures/futures_quotes.csv")
NOWCAST_FILE = Path("data/macro/inflation_nowcast.csv")
LOG_PATH = ROOT / "work" / "market_snapshot.log"
FUTURES = {"ES=F": "S&P 500 E-mini futures", "NQ=F": "Nasdaq-100 E-mini futures"}
NOWCAST_URL = "https://www.clevelandfed.org/-/media/files/webcharts/inflationnowcasting/nowcast_month.json"
NOWCAST_MONTHS = 3
STAMP_COLUMNS = ["snapshot_utc", "snapshot_et", "slot"]
FUTURES_COLUMNS = STAMP_COLUMNS + [
    "symbol", "name", "last_price", "last_bar_et", "delay_min", "ref_4pm_price", "ref_4pm_bar_et",
    "change_since_4pm_pct"]
NOWCAST_COLUMNS = STAMP_COLUMNS + ["target_month", "series", "value_mom_pct", "as_of", "source_updated"]


def log(message: str) -> None:
    line = f"[{pd.Timestamp.now(tz=NY):%Y-%m-%d %H:%M:%S} ET] {message}"
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as stream:
        stream.write(line + "\n")
    print(line, flush=True)  # no-op under pythonw


def slot_for(now: pd.Timestamp) -> str:
    """'morning' before the 9:30 open, 'close' just after the 4:00 close, else 'manual'."""
    t = now.tz_convert(NY)
    minutes = t.hour * 60 + t.minute
    if 8 * 60 <= minutes < 9 * 60 + 30:
        return "morning"
    if 16 * 60 <= minutes <= 16 * 60 + 45:
        return "close"
    return "manual"


def at_et(day, hour: int, minute: int = 0) -> pd.Timestamp:
    return pd.Timestamp(datetime.combine(pd.Timestamp(day).date(), wall_clock(hour, minute))).tz_localize(NY)


def last_close_time(now: pd.Timestamp) -> pd.Timestamp:
    """4:00 PM ET of the latest equity session whose close has already happened."""
    day = now.tz_convert(NY).date()
    sessions = equity_sessions(day - timedelta(days=14), day)
    return [at_et(s, 16) for s in sessions if at_et(s, 16) <= now][-1]


def num(value) -> float | None:
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def stamps(stamp: pd.Timestamp, slot: str) -> dict:
    return {"snapshot_utc": stamp.tz_convert("UTC").isoformat(timespec="seconds"),
            "snapshot_et": stamp.tz_convert(NY).isoformat(timespec="seconds"), "slot": slot}


# --- Futures (Yahoo) ----------------------------------------------------------------------------

def yahoo_bars(symbol: str) -> pd.DataFrame:
    """One-minute bars for the last few days (Yahoo delays CME quotes by about 10 minutes)."""
    import yfinance as yf
    return yf.Ticker(symbol).history(period="5d", interval="1m", auto_adjust=False)


def futures_row(symbol: str, bars: pd.DataFrame, stamp: pd.Timestamp, slot: str) -> dict | None:
    closes = bars["Close"].dropna() if "Close" in bars else pd.Series(dtype=float)
    if closes.empty:
        return None
    index = closes.index.tz_convert(NY) if closes.index.tz is not None else closes.index.tz_localize("UTC").tz_convert(NY)
    closes = pd.Series(closes.to_numpy(dtype=float), index=index)
    last_at, last = closes.index[-1], float(closes.iloc[-1])
    before = closes[closes.index < last_close_time(stamp)]
    ref_at, ref = (before.index[-1], float(before.iloc[-1])) if len(before) else (None, None)
    return {**stamps(stamp, slot), "symbol": symbol, "name": FUTURES.get(symbol, symbol),
            "last_price": last, "last_bar_et": last_at.isoformat(),
            "delay_min": round((stamp - last_at).total_seconds() / 60, 1),
            "ref_4pm_price": ref, "ref_4pm_bar_et": ref_at.isoformat() if ref_at is not None else None,
            "change_since_4pm_pct": round((last / ref - 1) * 100, 4) if ref else None}


def collect_futures(bars_for=yahoo_bars) -> tuple[list[tuple[str, pd.DataFrame]], list[str]]:
    found, problems = [], []
    for symbol in FUTURES:
        try:
            found.append((symbol, bars_for(symbol)))
        except Exception as exc:
            problems.append(f"{symbol}: {exc}")
    return found, problems


# --- Cleveland Fed inflation nowcast ------------------------------------------------------------

def cleveland_nowcast() -> list:
    response = requests.get(NOWCAST_URL, timeout=90,
                            headers={"User-Agent": "index-research-snapshot/0.1 (personal research script)"})
    response.raise_for_status()
    return json.loads(response.content.decode("utf-8-sig"))


TOOLTIP_DATE = re.compile(r"\{br\}(\d{1,2})/(\d{1,2})\{br\}")


def nowcast_rows(payload: list, stamp: pd.Timestamp, slot: str, months: int = NOWCAST_MONTHS) -> list[dict]:
    """Latest value of each series for the newest target months (nowcasts, and actuals once out).

    A series can have fewer points than the chart has day labels, so each point is dated from
    its own tooltip ("CPI Inflation{br}11/06{br}0.24"), not from its position."""
    rows = []
    for item in payload[-months:]:
        chart = item.get("chart") or {}
        year, month = (int(x) for x in str(chart.get("subcaption", "0-0")).split("-")[:2])
        labels = [c.get("label") for c in ((item.get("categories") or [{}])[0].get("category") or [])]
        for series in item.get("dataset") or []:
            points, latest = series.get("data") or [], None
            for i, point in enumerate(points):
                value = num(point.get("value"))
                if value is None:
                    continue
                found = TOOLTIP_DATE.search(point.get("tooltext") or "")
                if found:
                    day = (int(found.group(1)), int(found.group(2)))
                elif len(points) == len(labels):
                    day = tuple(int(x) for x in labels[i].split("/"))
                else:
                    continue  # can't date this point safely
                latest = (value, day)
            if latest is None:
                continue
            value, (label_month, label_day) = latest
            as_of = datetime(year + (label_month < month), label_month, label_day).date()
            rows.append({**stamps(stamp, slot), "target_month": f"{year}-{month:02d}",
                         "series": series.get("seriesname"), "value_mom_pct": round(value, 4),
                         "as_of": as_of.isoformat(), "source_updated": chart.get("_comment")})
    return rows


# --- Writing and the run ------------------------------------------------------------------------

def append_rows(path: Path, rows: list[dict], columns: list[str]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.exists() or path.stat().st_size == 0
    with path.open("a", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, extrasaction="ignore", lineterminator="\n")
        if new:
            writer.writeheader()
        writer.writerows(rows)


def wait_for_build(root: Path, sleep, lock_state, limit: int = 600) -> int:
    """Seconds spent waiting for a running build, so data/ doesn't change underneath it."""
    waited = 0
    while lock_state(root)["busy"] and waited < limit:
        sleep(15)
        waited += 15
    return waited


def run(root: Path = ROOT, *, scheduled: bool = False, bars_for=yahoo_bars, nowcast=cleveland_nowcast,
        now=lambda: pd.Timestamp.now(tz=NY), sleep=time.sleep, say=log, lock_state=build_lock_state,
        headlines=None, network=None) -> int:
    stamp = now()
    slot = slot_for(stamp)
    if scheduled and slot == "manual":
        say(f"Started at {stamp:%H:%M} ET, outside the 8:00-9:30 AM and 4:00-4:45 PM ET windows; skipped.")
        return 0
    if network:  # after a wake from sleep, Wi-Fi can take a while to reconnect
        network()
    problems: list[str] = []
    futures, futures_problems = collect_futures(bars_for)
    problems += futures_problems
    payload = None
    if slot != "morning":  # the nowcast updates once a day, so the 4:05 PM run is enough
        try:
            payload = nowcast()
        except Exception as exc:
            problems.append(f"Cleveland Fed nowcast: {exc}")
    futures_rows = [row for symbol, bars in futures if (row := futures_row(symbol, bars, stamp, slot))]
    try:
        cast_rows = nowcast_rows(payload, stamp, slot) if payload else []
    except Exception as exc:
        cast_rows = []
        problems.append(f"Cleveland Fed nowcast format: {exc}")
    waited = wait_for_build(root, sleep, lock_state)
    for path, rows, columns in ((FUTURES_FILE, futures_rows, FUTURES_COLUMNS), (NOWCAST_FILE, cast_rows, NOWCAST_COLUMNS)):
        append_rows(root / path, rows, columns)
    say(f"{slot.capitalize()} snapshot: {len(futures_rows)} futures, {len(cast_rows)} nowcast values"
        + (f"; waited {waited}s for a build" if waited else "")
        + (f". Problems: {'; '.join(problems)}" if problems else "."))
    if headlines:  # also archive headlines, so the morning page has news from before the open
        try:
            say(f"Headlines: {headlines(root)}")
        except Exception as exc:
            say(f"Headlines failed: {exc}")
    wrote = futures_rows or cast_rows
    return 0 if wrote and not problems else 1 if wrote else 2


def collect_headlines(root: Path) -> str:
    """Yahoo headlines for the three index ETFs and Fed releases, added to the first-seen archive."""
    from intraday_collect import refresh_headlines
    from news_history import archive_current
    results = refresh_headlines(root, ["SPY", "QQQ", "IWM"])
    added = archive_current(root)
    failed = [r["source"] for r in results if r["status"].startswith("failed")]
    return f"{added['added']} new, {added['total']} archived" + (f"; failed: {', '.join(failed)}" if failed else "")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--scheduled", action="store_true",
                        help="skip when started outside the snapshot windows (used by the scheduled task)")
    args = parser.parse_args(argv)
    try:
        import unattended
        with unattended.keep_awake():  # a timer-woken laptop would otherwise go back to sleep mid-run
            return run(ROOT, scheduled=args.scheduled, headlines=collect_headlines,
                       network=lambda: unattended.wait_for_network(log))
    except Exception:
        log("Snapshot failed:\n" + traceback.format_exc())
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
