"""Twice-daily Kalshi snapshots: the index/ETF perps right after the stock close and before the open.

The scheduled task "Trading Research Kalshi Snapshots" runs this on weekdays at 8:00 AM and
3:05 PM Central (9:00 AM and 4:05 PM ET). Kalshi doesn't serve past bid/ask prices or order
books, so these files are the only record of them:

  data/kalshi/perp_quotes.csv   one row per universe perp: bid/ask and sizes, mark and reference
                                (index) price, funding estimate, open interest, volume, and the
                                dollar depth of the order book within 5 and 25 bp of the mid
  data/kalshi/event_quotes.csv  one row per open market in Kalshi's CPI, core CPI, Fed decision
                                and payrolls series: yes bid/ask, last price, volume, open interest

Public market-data endpoints only: no account, no keys, never a trading endpoint. Rows are only
appended, and only after any running build finishes (an offline rebuild refuses to publish if its
inputs change). The evening task's git backup commits both files. Log: work/kalshi_snapshot.log.
"""
from __future__ import annotations

import argparse
import csv
import math
import time
import traceback
from pathlib import Path

import pandas as pd

from app_control import build_lock_state
from leverage.kalshi import INDEX_PERPS, _get
from validation import NY

ROOT = Path(__file__).resolve().parent
PERP_FILE = Path("data/kalshi/perp_quotes.csv")
EVENT_FILE = Path("data/kalshi/event_quotes.csv")
LOG_PATH = ROOT / "work" / "kalshi_snapshot.log"
EVENT_SERIES = ("KXCPI", "KXCPICORE", "KXFEDDECISION", "KXPAYROLLS")
DEPTH_BP = (5, 25)
PERP_COLUMNS = ["snapshot_utc", "snapshot_et", "slot", "ticker", "name", "status", "is_open",
                "bid", "ask", "mid", "spread_bp", "bid_size", "ask_size", "last_price", "mark_price",
                "reference_price", "reference_utc", "premium_bp", "funding_rate_estimate", "next_funding_utc",
                "open_interest", "open_interest_usd", "volume_24h", "volume_24h_usd", "book_levels",
                "bid_depth_5bp_usd", "ask_depth_5bp_usd", "bid_depth_25bp_usd", "ask_depth_25bp_usd"]
EVENT_COLUMNS = ["snapshot_utc", "snapshot_et", "slot", "series", "event_ticker", "ticker", "outcome",
                 "floor_strike", "cap_strike", "strike_type", "status", "close_time", "yes_bid", "yes_ask",
                 "yes_bid_size", "yes_ask_size", "last_price", "volume_24h", "volume", "open_interest"]


def log(message: str) -> None:
    line = f"[{pd.Timestamp.now(tz=NY):%Y-%m-%d %H:%M:%S} ET] {message}"
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as stream:
        stream.write(line + "\n")
    print(line, flush=True)  # no-op under pythonw


def slot_for(now: pd.Timestamp) -> str:
    """'morning' before the 9:30 open, 'close' just after the 4:00 close and funding, else 'manual'."""
    t = now.tz_convert(NY)
    minutes = t.hour * 60 + t.minute
    if 8 * 60 <= minutes < 9 * 60 + 30:
        return "morning"
    if 16 * 60 <= minutes <= 16 * 60 + 45:
        return "close"
    return "manual"


def num(value) -> float | None:
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def price(value) -> float | None:
    """A usable perp price. Kalshi sends 922337203685477.5807 (the 64-bit integer limit) when a
    side has no quote; treat that, and anything non-positive, as missing."""
    x = num(value)
    return x if x is not None and 0 < x < 1e6 else None


def book_levels(book: dict | None) -> tuple[list, list]:
    """(price, contracts) levels; a contract's notional value in dollars equals its price."""
    def clean(levels):
        out = [(price(p), num(s)) for p, s in levels or []]
        return [(p, s) for p, s in out if p and s]
    return clean((book or {}).get("bids")), clean((book or {}).get("asks"))


def depth_usd(levels: list, mid: float | None, bp: float, side: str) -> float | None:
    """Dollar value resting within `bp` basis points of the mid on one side of the book."""
    if not mid:
        return None
    if side == "bid":
        edge = mid * (1 - bp / 1e4)
        return round(sum(p * s for p, s in levels if p >= edge), 2)
    edge = mid * (1 + bp / 1e4)
    return round(sum(p * s for p, s in levels if p <= edge), 2)


def stamps(stamp: pd.Timestamp) -> dict:
    return {"snapshot_utc": stamp.tz_convert("UTC").isoformat(timespec="seconds"),
            "snapshot_et": stamp.tz_convert(NY).isoformat(timespec="seconds")}


def perp_row(market: dict, book: dict | None, estimate: dict | None, stamp: pd.Timestamp, slot: str) -> dict:
    bids, asks = book_levels(book)
    bid = price(market.get("bid")) or (max(p for p, _ in bids) if bids else None)
    ask = price(market.get("ask")) or (min(p for p, _ in asks) if asks else None)
    mid = (bid + ask) / 2 if bid and ask else None
    reference = market.get("reference_price") or {}
    ref, ref_ms = price(reference.get("price")), reference.get("ts_ms")
    next_funding = (estimate or {}).get("next_funding_time")  # inactive markets report year 0001
    row = {**stamps(stamp), "slot": slot, "ticker": market.get("ticker"),
           "name": INDEX_PERPS.get(market.get("ticker"), {}).get("name"), "status": market.get("status"),
           "is_open": (market.get("schedule") or {}).get("is_open"),
           "bid": bid, "ask": ask, "mid": mid, "spread_bp": round((ask - bid) / mid * 1e4, 3) if mid else None,
           "bid_size": num(market.get("bid_size_fp")), "ask_size": num(market.get("ask_size_fp")),
           "last_price": price(market.get("price")),
           "mark_price": price((market.get("liquidation_mark_price") or {}).get("price")),
           "reference_price": ref,
           "reference_utc": pd.Timestamp(int(ref_ms), unit="ms", tz="UTC").isoformat() if ref_ms else None,
           "premium_bp": round((mid / ref - 1) * 1e4, 3) if mid and ref else None,
           "funding_rate_estimate": num((estimate or {}).get("funding_rate")),
           "next_funding_utc": next_funding if next_funding and not next_funding.startswith("0001-") else None,
           "open_interest": num(market.get("open_interest")),
           "open_interest_usd": num(market.get("open_interest_notional_value_dollars")),
           "volume_24h": num(market.get("volume_24h")),
           "volume_24h_usd": num(market.get("volume_24h_notional_value_dollars")),
           "book_levels": len(bids) + len(asks) if book is not None else None}
    for bp in DEPTH_BP:
        row[f"bid_depth_{bp}bp_usd"] = depth_usd(bids, mid, bp, "bid") if book is not None else None
        row[f"ask_depth_{bp}bp_usd"] = depth_usd(asks, mid, bp, "ask") if book is not None else None
    return row


def event_rows(markets: list[dict], series: str, stamp: pd.Timestamp, slot: str) -> list[dict]:
    return [{**stamps(stamp), "slot": slot, "series": series, "event_ticker": m.get("event_ticker"),
             "ticker": m.get("ticker"), "outcome": m.get("yes_sub_title"), "floor_strike": m.get("floor_strike"),
             "cap_strike": m.get("cap_strike"), "strike_type": m.get("strike_type"), "status": m.get("status"),
             "close_time": m.get("close_time"), "yes_bid": num(m.get("yes_bid_dollars")),
             "yes_ask": num(m.get("yes_ask_dollars")), "yes_bid_size": num(m.get("yes_bid_size_fp")),
             "yes_ask_size": num(m.get("yes_ask_size_fp")), "last_price": num(m.get("last_price_dollars")),
             "volume_24h": num(m.get("volume_24h_fp")), "volume": num(m.get("volume_fp")),
             "open_interest": num(m.get("open_interest_fp"))} for m in markets]


def collect(get=_get) -> tuple[list, list, list[str]]:
    """Fetch everything first so the snapshot reflects one moment; record problems, don't stop."""
    problems: list[str] = []
    listed = {m.get("ticker"): m for m in get("/margin/markets", {"limit": 1000}).get("markets", [])}
    perps = []
    for ticker in INDEX_PERPS:
        market = listed.get(ticker)
        if market is None:
            problems.append(f"{ticker} is not listed")
            continue
        book = estimate = None
        try:
            book = get(f"/margin/markets/{ticker}/orderbook").get("orderbook") or {}
        except Exception as exc:
            problems.append(f"{ticker} order book: {exc}")
        try:
            estimate = get("/margin/funding_rates/estimate", {"ticker": ticker})
        except Exception as exc:
            problems.append(f"{ticker} funding estimate: {exc}")
        perps.append((market, book, estimate))
    events = []
    for series in EVENT_SERIES:
        try:
            events.append((series, get("/markets", {"series_ticker": series, "status": "open", "limit": 1000}).get("markets", [])))
        except Exception as exc:
            problems.append(f"{series}: {exc}")
    return perps, events, problems


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


def run(root: Path = ROOT, *, scheduled: bool = False, get=_get, now=lambda: pd.Timestamp.now(tz=NY),
        sleep=time.sleep, say=log, lock_state=build_lock_state) -> int:
    stamp = now()
    slot = slot_for(stamp)
    if scheduled and slot == "manual":
        say(f"Started at {stamp:%H:%M} ET, outside the 8:00-9:30 AM and 4:00-4:45 PM ET windows; skipped.")
        return 0
    perps, events, problems = collect(get)
    perp_rows = [perp_row(market, book, estimate, stamp, slot) for market, book, estimate in perps]
    quote_rows = [row for series, markets in events for row in event_rows(markets, series, stamp, slot)]
    waited = wait_for_build(root, sleep, lock_state)
    append_rows(root / PERP_FILE, perp_rows, PERP_COLUMNS)
    append_rows(root / EVENT_FILE, quote_rows, EVENT_COLUMNS)
    opened = sum(1 for row in perp_rows if row["is_open"])
    say(f"{slot.capitalize()} snapshot: {len(perp_rows)} perps ({opened} open), {len(quote_rows)} event markets"
        + (f"; waited {waited}s for a build" if waited else "")
        + (f". Problems: {'; '.join(problems)}" if problems else "."))
    return 0 if perp_rows and not problems else 1 if perp_rows else 2


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--scheduled", action="store_true",
                        help="skip when started outside the snapshot windows (used by the scheduled task)")
    args = parser.parse_args(argv)
    try:
        return run(ROOT, scheduled=args.scheduled)
    except Exception:
        log("Snapshot failed:\n" + traceback.format_exc())
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
