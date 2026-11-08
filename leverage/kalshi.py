"""Download Kalshi perpetual-futures ("perps") data.

Every endpoint used here is public market data: no Kalshi account or API key is needed.
  - /margin/markets ..................... every perp: price, bid/ask, leverage, volume, open interest, hours
  - /margin/risk_parameters ............. how far margin can fall before liquidation
  - /margin/funding_rates/historical .... every funding payment since each perp launched (one call)
  - /margin/markets/{ticker}/candlesticks hourly prices for the index perps

Downloads are saved under data/raw/kalshi/ so --offline works. Each run also appends the market
list to data/kalshi/snapshots.csv. Kalshi doesn't serve old spreads or open interest, so that file
is the only way to build up their history. It is kept out of data/raw/ on purpose.
"""

from __future__ import annotations

import json
import time
import math
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw" / "kalshi"
SNAPSHOTS = ROOT / "data" / "kalshi" / "snapshots.csv"

PLATFORM = "Kalshi"
BASE = "https://external-api.kalshi.com/trade-api/v2"
HEADERS = {"User-Agent": "index-research-leverage/0.1 (personal research script)"}

# The perps that follow the markets on the Indexes tab, and the ETF whose history stands in for
# each one. US500 and US Tech 100 follow their own indexes (S&P 500-style and Nasdaq-100-style),
# so how closely they track SPY and QQQ is measured, not assumed.
INDEX_PERPS = {
    "KXUS500PERP": {"name": "US500", "proxy": "SPY", "tracks": "US large-cap index (S&P 500-style, by MerQube)"},
    "KXUSTECH100PERP": {"name": "US Tech 100", "proxy": "QQQ", "tracks": "US tech-100 index (Nasdaq-100-style)"},
    "KXSPYPERP": {"name": "SPY", "proxy": "SPY", "tracks": "SPY ETF"},
    "KXQQQPERP": {"name": "QQQ", "proxy": "QQQ", "tracks": "QQQ ETF"},
    "KXUS2000PERP": {"name": "US 2000", "proxy": "IWM", "tracks": "US small-cap index (Russell 2000-style)"},
}


def _get(path: str, params: dict | None = None, tries: int = 3) -> dict:
    last = None
    for attempt in range(tries):
        try:
            r = requests.get(BASE + path, params=params, headers=HEADERS, timeout=60)
            if r.status_code == 429:  # rate limited: back off
                time.sleep(2 * (attempt + 1))
                continue
            r.raise_for_status()
            return r.json()
        except (requests.RequestException, ValueError) as e:
            last = e
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"Could not download {path}: {last}")


def _validate_payload(name: str, value: dict, previous: dict | None = None) -> None:
    """Reject malformed/partial replacements before touching the last usable cache."""
    if not isinstance(value, dict):
        raise ValueError(f"{name}: expected a JSON object")
    def number(v, *, positive=False):
        try:
            x = float(v)
        except (ValueError, TypeError):
            raise ValueError(f"{name}: invalid numeric value") from None
        if not math.isfinite(x) or (positive and x <= 0):
            raise ValueError(f"{name}: nonfinite or nonpositive value")
        return x
    if name == "markets.json":
        records = value.get("markets")
        if not isinstance(records, list) or not records:
            raise ValueError("Market list is empty or missing")
        tickers = [m.get("ticker") for m in records if isinstance(m, dict)]
        if len(tickers) != len(records) or any(not isinstance(t, str) or not t for t in tickers) or len(set(tickers)) != len(tickers):
            raise ValueError("Invalid or duplicate market tickers")
        for m in records:
            if m.get("status") not in {"active", "inactive", "closed"}:
                raise ValueError("Unexpected market status")
            number(m.get("price"), positive=m.get("status") == "active")
        if previous and not {m["ticker"] for m in previous.get("markets", [])} <= set(tickers):
            raise ValueError("Candidate market list loses cached markets; retain prior data pending review")
    elif name == "risk_parameters.json":
        mults = value.get("initial_margin_multiplier")
        if not isinstance(mults, dict) or not mults:
            raise ValueError("Initial-margin multipliers are missing")
        if any(number(v, positive=True) <= 1 for v in mults.values()):
            raise ValueError("Initial-margin multipliers must exceed one")
        for field in ("liquidation_margin_ratio_threshold", "queue_entry_margin_ratio_threshold"):
            number(value.get(field), positive=True)
    elif name == "funding_history.json":
        records = value.get("funding_rates")
        if not isinstance(records, list) or not records:
            raise ValueError("Funding history is empty or missing")
        keys = []
        for r in records:
            stamp = pd.to_datetime(r.get("funding_time"), utc=True, errors="coerce")
            if pd.isna(stamp) or not r.get("market_ticker"):
                raise ValueError("Invalid funding timestamp/ticker")
            number(r.get("funding_rate")); number(r.get("mark_price"), positive=True)
            keys.append((r["market_ticker"], stamp.isoformat()))
        if len(set(keys)) != len(keys):
            raise ValueError("Duplicate funding records")
        old = {(r["market_ticker"], pd.Timestamp(r["funding_time"]).isoformat()) for r in (previous or {}).get("funding_rates", [])}
        if not old <= set(keys):
            raise ValueError("Candidate funding history loses cached records")
    elif name.startswith("hourly_"):
        records = value.get("candlesticks")
        if not isinstance(records, list) or not records:
            raise ValueError("Hourly candles are empty or missing")
        stamps = []
        for r in records:
            stamp = number(r.get("end_period_ts"), positive=True)
            if stamp != int(stamp):
                raise ValueError("Candle timestamp must be an integer")
            stamps.append(int(stamp))
            prices = r.get("price") or {}
            numeric = {k: number(prices[k], positive=True) for k in ("open", "high", "low", "close") if prices.get(k) not in (None, "")}
            if all(k in numeric for k in ("open", "high", "low", "close")) and (numeric["high"] < max(numeric.values()) or numeric["low"] > min(numeric.values())):
                raise ValueError("Candle OHLC range is inconsistent")
        if len(set(stamps)) != len(stamps) or stamps != sorted(stamps):
            raise ValueError("Hourly candles are duplicate or unordered")
        if not {int(r["end_period_ts"]) for r in (previous or {}).get("candlesticks", [])} <= set(stamps):
            raise ValueError("Candidate hourly history loses cached candles")


def _cached(name: str, fetch, offline: bool, status: dict, label: str):
    """Validate before an atomic replacement; an offline read never refreshes timestamps."""
    RAW.mkdir(parents=True, exist_ok=True)
    path = RAW / name
    previous = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
    if previous is not None:
        _validate_payload(name, previous)
    how = "offline" if offline else "downloaded"
    if not offline:
        temporary = path.with_suffix(path.suffix + ".tmp")
        try:
            candidate = fetch()
            _validate_payload(name, candidate, previous)
            temporary.write_text(json.dumps(candidate, allow_nan=False), encoding="utf-8")
            temporary.replace(path)
        except (RuntimeError, ValueError, OSError) as e:
            if temporary.exists():
                temporary.unlink()
            if previous is None:
                raise
            print(f"  {name}: {e}; preserving the last validated cache.")
            how = "failed"
    if not path.exists():
        raise RuntimeError(f"No cached {name}; an offline run cannot invent data")
    saved = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    prev = status.get(label)
    rank = {"downloaded": 0, "offline": 1, "failed": 2}
    if prev is None or rank[how] > rank[prev["how"]]:
        status[label] = {"how": how, "saved": saved}
    return json.loads(path.read_text(encoding="utf-8"))


def _append_snapshot(markets: list[dict]) -> None:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    rows = [{
        "snapshot_utc": now,
        "platform": PLATFORM,
        "ticker": m.get("ticker"),
        "title": m.get("title"),
        "asset_class": m.get("asset_class"),
        "status": m.get("status"),
        "bid": m.get("bid"),
        "ask": m.get("ask"),
        "price": m.get("price"),
        "leverage_estimate": m.get("leverage_estimate"),
        "volume_24h_usd": m.get("volume_24h_notional_value_dollars"),
        "open_interest_usd": m.get("open_interest_notional_value_dollars"),
        "is_open": (m.get("schedule") or {}).get("is_open"),
    } for m in markets]
    SNAPSHOTS.parent.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(rows)
    df.to_csv(SNAPSHOTS, mode="a", header=not SNAPSHOTS.exists(), index=False, lineterminator="\n")


def _hourly(ticker: str, start: datetime, end: datetime) -> list[dict]:
    """Hourly candles, fetched a week at a time to keep each response small."""
    out, cur = [], int(start.timestamp())
    stop = int(end.timestamp())
    while cur < stop:
        nxt = min(cur + 7 * 86400, stop)
        data = _get(f"/margin/markets/{ticker}/candlesticks",
                    {"start_ts": cur, "end_ts": nxt, "period_interval": 60})
        out.extend(data.get("candlesticks", []))
        cur = nxt
        time.sleep(0.2)
    seen, unique = set(), []
    for c in out:  # chunk edges can repeat a candle
        if c["end_period_ts"] not in seen:
            seen.add(c["end_period_ts"])
            unique.append(c)
    return sorted(unique, key=lambda c: c["end_period_ts"])


def fetch_all(offline: bool = False) -> dict:
    status: dict = {}
    label = "Kalshi perps (public API)"
    print("Downloading Kalshi perp markets..." if not offline else "Loading saved Kalshi perp markets...")
    markets = _cached("markets.json", lambda: _get("/margin/markets", {"limit": 1000}), offline, status, label)["markets"]
    if status[label]["how"] == "downloaded":
        _append_snapshot(markets)
    risk = _cached("risk_parameters.json", lambda: _get("/margin/risk_parameters"), offline, status, label)
    print("Downloading Kalshi funding history..." if not offline else "Loading saved Kalshi funding history...")
    funding = _cached("funding_history.json", lambda: _get("/margin/funding_rates/historical"), offline, status, label)

    fund = pd.DataFrame(funding.get("funding_rates", []))
    if len(fund):
        fund["funding_time"] = pd.to_datetime(fund["funding_time"], utc=True)
        fund["funding_rate"] = pd.to_numeric(fund["funding_rate"], errors="coerce")
        fund["mark_price"] = pd.to_numeric(fund["mark_price"], errors="coerce")
    live = {m["ticker"] for m in markets if m.get("status") == "active"}

    print("Downloading hourly prices for the index perps..." if not offline else "Loading saved hourly prices...")
    hourly = {}
    now = datetime.now(timezone.utc)
    for ticker in INDEX_PERPS:
        if ticker not in live:
            continue
        first = fund.loc[fund["market_ticker"] == ticker, "funding_time"].min() if len(fund) else None
        start = (first - pd.Timedelta(days=2)).to_pydatetime() if first is not None and pd.notna(first) else now - pd.Timedelta(days=7)
        data = _cached(f"hourly_{ticker}.json", lambda t=ticker, s=start: {"candlesticks": _hourly(t, s, now)}, offline, status, label)
        hourly[ticker] = data["candlesticks"]

    snaps = pd.read_csv(SNAPSHOTS) if SNAPSHOTS.exists() else pd.DataFrame()
    return {"markets": markets, "risk": risk, "funding": fund, "hourly": hourly, "status": status,
            "snapshots": snaps, "fetched_utc": datetime.fromtimestamp((RAW / "markets.json").stat().st_mtime, tz=timezone.utc)}
