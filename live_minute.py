"""Live minute bars: poll Yahoo's free one-minute bars once a minute through the regular session.

Review A1 (2026-11-18; user: "poll yahoo", "Yahoo, no account"). Run by the scheduled task "Trading Research Live
Minute Bars" (Mon-Fri 8:28 AM Central, and two minutes after sign-in). It waits for the open, then 5 seconds
after each minute polls every ticker in collection.live_minute_symbols (terminal_config.json; one request covers
them all; change the list there) and stores each completed regular-session bar in the day's small journal
data/intraday/v1/live/<date>.jsonl (intraday.store.ingest_live) with:
- timestamp: the bar's start; it completed 60 seconds later;
- available_at: when this app received it (the poll's receipt time);
- source: "Yahoo Finance / yfinance (live poll)";
- availability_basis: "observed_live" only if this app first received the bar within LIVE_DELAY (120 seconds)
  of its close; a bar first seen later (the poller started late, the laptop slept, Yahoo lagged) is
  "retrieved_archive". A later poll with different values for a stored bar is appended as a revision with its
  own receipt time and the same label as the bar's first receipt. Existing archive bars are never relabelled.
Yahoo's bars are free and indicative and may be delayed: they are not exchange-verified or executable quotes.
It stops just after the exchange calendar's close (1 PM ET on early closes) and holds the laptop awake while it
runs. While a build is running it keeps its bars in memory (an offline build refuses to publish if data/
changes under it) and stores them afterwards, receipt times unchanged.
Status: data/terminal/live_minute_status.json (polls, gaps, bars per ticker), shown in System status.
Log: work/live_minute.log. Exit codes: 0 done (or not a trading day); 2 no bar stored; 3 unexpected error.
"""
from __future__ import annotations

import json
import os
import time
import traceback
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent
LOG_PATH = ROOT / "work" / "live_minute.log"
STATUS = Path("data/terminal/live_minute_status.json")
NY = "America/New_York"
LIVE_DELAY = 120   # seconds after a bar's close within which a first receipt counts as observed live
OFFSET = 5         # seconds after each minute boundary to poll, so the bar that just closed is published
GAP = 150          # seconds between polls beyond which the status lists a gap
SOURCE = "Yahoo Finance / yfinance (live poll)"


def log(message: str) -> None:
    line = f"[{pd.Timestamp.now(tz=NY):%Y-%m-%d %H:%M:%S} ET] {message}"
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as stream:
        stream.write(line + "\n")
    print(line, flush=True)  # no-op under pythonw


def yahoo_minutes(symbols: list[str]) -> dict[str, pd.DataFrame]:
    """Today's regular-session one-minute bars per ticker, as Yahoo serves them now (the last row may be open)."""
    import yfinance as yf
    frame = yf.download(list(symbols), period="1d", interval="1m", prepost=False, auto_adjust=False,
                        group_by="ticker", progress=False, threads=True)
    out = {}
    for symbol in symbols:
        try:
            part = frame[symbol] if isinstance(frame.columns, pd.MultiIndex) else frame
        except KeyError:
            continue
        out[symbol] = part.dropna(subset=["Open", "High", "Low", "Close"])
    return out


def records(symbol: str, frame: pd.DataFrame, receipt: pd.Timestamp, bounds: tuple, first_seen: dict) -> list[dict]:
    """Store records for this poll's completed regular-session bars. `first_seen` maps (symbol, start) to the
    first receipt time and is updated, so a revision keeps the label of the bar's first receipt."""
    opened, closed = bounds
    out = []
    for at, row in frame.iterrows():
        start = pd.Timestamp(at).tz_convert("UTC")
        done = start + pd.Timedelta(seconds=60)
        if start < opened or start >= closed or done > receipt or start.value % 60_000_000_000:
            continue  # outside the session, still open, or not on a whole minute
        values = {k: float(row[k.title()]) for k in ("open", "high", "low", "close", "volume")}
        if not all(pd.notna(v) for v in values.values()):
            continue
        first = first_seen.setdefault((symbol, start.isoformat()), receipt)
        live = (first - done).total_seconds() <= LIVE_DELAY
        out.append({"symbol": symbol, "timestamp": start.isoformat(), "available_at": receipt.isoformat(),
                    "interval_seconds": 60, "source": SOURCE, **values,
                    "availability_basis": "observed_live" if live else "retrieved_archive"})
    return out


def _first_seen(root: Path, day: str) -> dict:
    """First receipt of each bar already stored today (so a restart keeps the original labels)."""
    from intraday import store
    path = store.live_folder(root) / f"{day}.jsonl"
    seen = {}
    for event in store.read_events(path) if path.exists() else []:
        bar = event["bar"]
        k, at = (bar["symbol"], pd.Timestamp(bar["timestamp"]).tz_convert("UTC").isoformat()), pd.Timestamp(bar["available_at"])
        if k not in seen or at < seen[k]:
            seen[k] = at
    return seen


def next_poll(now: pd.Timestamp, opened: pd.Timestamp) -> pd.Timestamp:
    """5 seconds after the next minute boundary, and never before the first bar has closed."""
    target = now.floor("min") + pd.Timedelta(seconds=OFFSET)
    if target <= now:
        target += pd.Timedelta(minutes=1)
    return max(target, opened + pd.Timedelta(seconds=60 + OFFSET))


def _write_status(root: Path, status: dict) -> None:
    path = Path(root) / STATUS
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(status, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(temp, path)


def run(root: Path = ROOT, *, now=lambda: pd.Timestamp.now(tz="UTC"), fetch=yahoo_minutes, sleep=time.sleep,
        say=log, symbols=None, busy=None) -> int:
    from intraday import store
    from intraday.calendar import session
    from terminal_config import live_minute_symbols
    if busy is None:
        from app_control import build_lock_state
        busy = lambda: build_lock_state(root)["busy"]  # noqa: E731
    symbols = symbols or live_minute_symbols(root)
    start = now()
    day = start.tz_convert(NY).strftime("%Y-%m-%d")
    info = session(day)
    if not info.get("is_session"):
        say(f"{day} is not a trading day; nothing to poll.")
        return 0
    opened, closed = pd.Timestamp(info["open"]), pd.Timestamp(info["close"])
    stop = closed + pd.Timedelta(seconds=60 + OFFSET)  # the last bar closes at the close; poll once after it
    if start > stop:
        say(f"The {day} session is over; nothing to poll.")
        return 0
    first_seen = _first_seen(root, day)
    status = {"date": day, "symbols": symbols, "started_utc": start.isoformat(timespec="seconds"), "running": True,
              "open_utc": opened.isoformat(), "close_utc": closed.isoformat(), "polls": 0, "failures": 0,
              "gaps": [], "bars": {}, "live_bars": {}, "late_bars": {}, "revisions": 0, "last_bar": {},
              "last_poll_utc": None, "live_delay_seconds": LIVE_DELAY,
              "note": "Yahoo's free one-minute bars: indicative, not exchange-verified, may be delayed."}
    if start > opened + pd.Timedelta(seconds=60 + LIVE_DELAY):
        status["gaps"].append([opened.isoformat(), start.isoformat(timespec="seconds")])  # started after the open
    say(f"Live minute bars for {', '.join(symbols)} on {day}: polling until {closed.tz_convert(NY):%H:%M} ET.")
    _write_status(root, status)
    pending, previous = [], None
    while True:
        target = next_poll(now(), opened)
        if target > stop:
            break
        sleep(max((target - now()).total_seconds(), 0))
        receipt = now()
        if previous is not None and (receipt - previous).total_seconds() > GAP:
            status["gaps"].append([previous.isoformat(timespec="seconds"), receipt.isoformat(timespec="seconds")])
        previous = receipt
        try:
            frames = fetch(symbols)
            for symbol in symbols:
                pending += records(symbol, frames.get(symbol, pd.DataFrame()), receipt, (opened, closed), first_seen)
            status["polls"] += 1
        except Exception as exc:
            status["failures"] += 1
            if status["failures"] in (1, 10, 100):
                say(f"Poll failed ({status['failures']} so far): {str(exc)[:160]}")
        if pending and not busy():
            try:
                stored = store.ingest_live(root, pending)
                status["revisions"] += stored["revisions"]
                for r in pending:
                    status["last_bar"][r["symbol"]] = max(status["last_bar"].get(r["symbol"], ""), r["timestamp"])
                pending = []
                status["bars"], status["live_bars"], status["late_bars"] = _counts(root, day)
            except Exception as exc:
                status["failures"] += 1
                say(f"Storing bars failed (kept for the next minute): {str(exc)[:160]}")
        status["last_poll_utc"] = receipt.isoformat(timespec="seconds")
        _write_status(root, status)
    if pending:
        try:
            store.ingest_live(root, pending)
            status["bars"], status["live_bars"], status["late_bars"] = _counts(root, day)
        except Exception as exc:
            say(f"Final store failed; {len(pending)} bar(s) not saved: {str(exc)[:160]}")
    status.update(running=False, finished_utc=now().isoformat(timespec="seconds"))
    _write_status(root, status)
    total = sum(status["bars"].values())
    say(f"Done: {status['polls']} polls, {status['failures']} failures, {len(status['gaps'])} gap(s); bars stored "
        + ", ".join(f"{s} {status['bars'].get(s, 0)} ({status['live_bars'].get(s, 0)} live)" for s in symbols) + ".")
    return 0 if total else 2


def _counts(root: Path, day: str) -> tuple[dict, dict, dict]:
    """Distinct bars stored today per ticker, and how many of them were first received live or late."""
    from intraday import store
    path = store.live_folder(root) / f"{day}.jsonl"
    first = {}
    for event in store.read_events(path) if path.exists() else []:
        bar = event["bar"]
        k = (bar["symbol"], bar["timestamp"])
        if k not in first or bar["available_at"] < first[k]["available_at"]:
            first[k] = bar
    bars, live, late = {}, {}, {}
    for (symbol, _), bar in first.items():
        bars[symbol] = bars.get(symbol, 0) + 1
        target = live if bar["availability_basis"] == "observed_live" else late
        target[symbol] = target.get(symbol, 0) + 1
    return bars, live, late


def main() -> int:
    try:
        import unattended
        with unattended.keep_awake():  # a timer-woken laptop would otherwise go back to sleep mid-session
            unattended.wait_for_network(log)
            return run(ROOT)
    except Exception:
        log("Live minute polling failed:\n" + traceback.format_exc())
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
