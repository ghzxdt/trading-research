"""Free share-liquidity data for the declared snapshot policy (the "snapshot" journal in liquidity_screen.py).

Two free sources, combined into one immutable record per instrument per trading day:

- Share bid/ask spreads, sampled four times a day from Yahoo (10:30 AM, 12:30, 2:30 and 3:50 PM ET). A day's
  spread is the median of its samples. That is NOT a full-session quote median, which is why these records live
  in their own journal and every result using them says so.
- Share volume: Yahoo's daily volume (full session).

The intraday shares gate (review C13) reads these. Options data is no longer collected (user's trim list,
2026-11-19): no option spreads in the samples and no OCC options volume; the OCC file and its layout check
(review C12: OCC counts both sides of each trade) are in archive/options-2026-11-19/. Older sample files still
carry their option fields; they are ignored.

After the close, `update()` writes each finished day's record once its samples and volume are in. Public data only.
"""
from __future__ import annotations

import json
import math
import statistics
from datetime import timedelta
from pathlib import Path

import pandas as pd

from validation import NY, equity_sessions

SAMPLES = Path("data/liquidity/samples")
MIN_SAMPLES = 3
SOURCE = "free-snapshot-v2: Yahoo quote samples (shares only since 2026-11-19); Yahoo daily volume"
METHOD = ("Share spread: median of up to 4 intraday Yahoo snapshots (10:30, 12:30, 14:30, 15:50 ET), not a "
          "full-session quote median. Share volume: Yahoo daily volume. No options metrics since 2026-11-19.")

def _bps(bid, ask):
    try:
        bid, ask = float(bid), float(ask)
    except (TypeError, ValueError):
        return None
    if not (math.isfinite(bid) and math.isfinite(ask)) or bid <= 0 or ask < bid:
        return None
    return (ask - bid) / ((ask + bid) / 2) * 1e4


def in_sampling_window(now: pd.Timestamp) -> bool:
    t = now.tz_convert(NY)
    day = t.tz_localize(None).normalize()
    return len(equity_sessions(day, day)) == 1 and (9 * 60 + 45) <= t.hour * 60 + t.minute <= (15 * 60 + 55)


# --- Sampling ------------------------------------------------------------------------------------

def yahoo_quote(symbol: str) -> dict:
    import yfinance as yf
    info = yf.Ticker(symbol).info
    # "time": Yahoo's reported last-trade time (epoch seconds), so the pre-close check can record the quote's age.
    return {"bid": info.get("bid"), "ask": info.get("ask"), "price": info.get("regularMarketPrice"),
            "time": info.get("regularMarketTime")}


def sample_symbol(symbol: str, now: pd.Timestamp, quote_for=yahoo_quote) -> dict:
    quote = quote_for(symbol)
    return {"symbol": symbol, "sampled_at": now.tz_convert("UTC").isoformat(timespec="seconds"),
            "share_bid": quote.get("bid"), "share_ask": quote.get("ask"),
            "share_spread_bps": _bps(quote.get("bid"), quote.get("ask"))}


def sample(root: Path, symbols: list[str], now: pd.Timestamp, quote_for=yahoo_quote) -> dict:
    """One snapshot of every instrument's share bid/ask spread, appended to today's file."""
    if not in_sampling_window(now):
        return {"sampled": 0, "skipped": "outside regular trading hours"}
    path = Path(root) / SAMPLES / f"{now.tz_convert(NY):%Y-%m-%d}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    rows, failed = [], []
    for symbol in symbols:
        try:
            rows.append(sample_symbol(symbol, now, quote_for))
        except Exception as exc:
            failed.append(f"{symbol}: {str(exc)[:120]}")
    with path.open("a", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row, sort_keys=True) + "\n")
    return {"sampled": len(rows), "failed": failed}


def load_samples(root: Path, day: str) -> list[dict]:
    path = Path(root) / SAMPLES / f"{day}.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def yahoo_daily_volume(symbol: str) -> dict[str, int]:
    import yfinance as yf
    frame = yf.Ticker(symbol).history(period="3mo", interval="1d", auto_adjust=False)
    return {f"{ts:%Y-%m-%d}": int(v) for ts, v in frame["Volume"].dropna().items()}


def day_record(symbol: str, day: str, samples: list[dict], share_volume: int | None, now: pd.Timestamp) -> dict | None:
    mine = [s for s in samples if s.get("symbol") == symbol]
    shares = [s["share_spread_bps"] for s in mine if s.get("share_spread_bps") is not None]
    if not shares or share_volume is None:
        return None
    stamp = now.tz_convert("UTC").isoformat()
    return {"symbol": symbol, "session_date": day, "complete_session": len(shares) >= MIN_SAMPLES,
            "source": SOURCE, "source_timestamp": stamp, "available_at": stamp, "spread_basis": "midpoint",
            "metric_method": METHOD, "share_volume": int(share_volume),
            "share_median_spread_bps": round(statistics.median(shares), 4),
            "options_volume": None, "options_median_spread_bps": None,
            "provenance": {"share_samples": len(shares), "sample_times": [s["sampled_at"] for s in mine]}}


def update(root: Path, symbols: list[str], now: pd.Timestamp, volume_for=yahoo_daily_volume, say=print,
           lookback: int = 20) -> dict:
    """After the close: write each finished day's record (share spread and volume) once its parts are in."""
    from liquidity_screen import _load, import_verified
    today = now.tz_convert(NY).tz_localize(None).normalize()
    finished = [d for d in equity_sessions(today - timedelta(days=45), today)
                if pd.Timestamp(f"{d:%Y-%m-%d} 16:15").tz_localize(NY) <= now][-lookback:]
    written = {k for k in _load(root, "snapshot")}
    records, volumes = [], {}
    for day in (f"{d:%Y-%m-%d}" for d in finished):
        samples = load_samples(root, day)
        if not samples:
            continue
        for symbol in symbols:
            if (symbol, day) in written:
                continue
            if symbol not in volumes:
                try:
                    volumes[symbol] = volume_for(symbol)
                except Exception:
                    volumes[symbol] = {}
            record = day_record(symbol, day, samples, volumes[symbol].get(day), now)
            if record:
                records.append(record)
    result = import_verified(root, records, journal="snapshot") if records else {"accepted": 0}
    say(f"Liquidity: {result['accepted']} day record(s) written to the snapshot journal.")
    return {"records": result["accepted"]}
