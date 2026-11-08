"""Free liquidity data for the declared snapshot policy (the "snapshot" journal in liquidity_screen.py).

Three free sources, combined into one immutable record per instrument per trading day:

- Share and option bid/ask spreads, sampled four times a day from Yahoo (10:30 AM, 12:30, 2:30 and 3:50 PM ET):
  the share quote, and option contracts in the nearest two expiries with strikes within 5% of the share price
  and two-sided quotes. A day's spread is the median of its samples. That is NOT a full-session quote median,
  which is why these records live in their own journal and every result using them says so.
- Share volume: Yahoo's daily volume (full session).
- Options volume: OCC's daily cleared volume for standard contracts on the underlying (adjusted contracts such as
  2SPY are left out). OCC appears to count both sides of each trade, so the one-sided estimate is half the
  total; if that is wrong it only understates volume, which is the safe direction for a minimum-volume test.

After the close, `update()` fetches missing OCC days and writes each finished day's record once every part is in
(or after three trading days without OCC's figure, with options volume left blank). Public data only.
"""
from __future__ import annotations

import io
import json
import math
import statistics
import time
from datetime import timedelta
from pathlib import Path

import pandas as pd
import requests

from validation import NY, equity_sessions

SAMPLES = Path("data/liquidity/samples")
OCC_FILE = Path("data/liquidity/occ_volume.csv")
OCC_URL = ("https://marketdata.theocc.com/volume-query?format=csv&volumeQueryType=O&symbolType=U&reportType=D"
           "&accountType=ALL&productKind=ALL&porc=BOTH&reportDate={day}&symbol={symbol}")
HEADERS = {"User-Agent": "index-research-liquidity/0.1 (personal research script)"}
BAND, EXPIRIES = 0.05, 2
MIN_SAMPLES = 3
OCC_PATIENCE = 3  # trading days to wait for OCC's figure before writing the day without it
SOURCE = "free-snapshot-v1: Yahoo quote and option-chain samples; Yahoo daily volume; OCC cleared volume"
METHOD = ("Spreads: median of up to 4 intraday Yahoo snapshots (10:30, 12:30, 14:30, 15:50 ET), not a full-session "
          "quote median; option spread per snapshot is the median over two-sided contracts in the nearest "
          f"{EXPIRIES} expiries with strikes within {BAND:.0%} of the share price. Share volume: Yahoo daily volume. "
          "Options volume: OCC cleared volume on standard contracts divided by 2 (one-sided estimate).")
SCOPE = {"expiries": f"nearest {EXPIRIES}", "strikes": f"within {BAND:.0%} of the share price",
         "quotes": "two-sided (bid > 0, ask >= bid)", "volume": "OCC standard contracts, cleared sides / 2"}


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
    return {"bid": info.get("bid"), "ask": info.get("ask"), "price": info.get("regularMarketPrice")}


def yahoo_near_chain(symbol: str, spot: float) -> list[dict]:
    import yfinance as yf
    ticker = yf.Ticker(symbol)
    rows = []
    for expiry in list(ticker.options)[:EXPIRIES]:
        chain = ticker.option_chain(expiry)
        for frame in (chain.calls, chain.puts):
            for _, r in frame.iterrows():
                if abs(float(r["strike"]) / spot - 1) <= BAND:
                    rows.append({"expiry": expiry, "strike": float(r["strike"]), "bid": r.get("bid"), "ask": r.get("ask")})
    return rows


def sample_symbol(symbol: str, now: pd.Timestamp, quote_for=yahoo_quote, chain_for=yahoo_near_chain) -> dict:
    quote = quote_for(symbol)
    share = _bps(quote.get("bid"), quote.get("ask"))
    spot = (float(quote["bid"]) + float(quote["ask"])) / 2 if share is not None else quote.get("price")
    row = {"symbol": symbol, "sampled_at": now.tz_convert("UTC").isoformat(timespec="seconds"),
           "share_bid": quote.get("bid"), "share_ask": quote.get("ask"), "share_spread_bps": share,
           "option_median_spread_bps": None, "option_contracts": 0}
    if spot:
        spreads = [s for s in (_bps(c.get("bid"), c.get("ask")) for c in chain_for(symbol, float(spot))) if s is not None]
        if spreads:
            row.update(option_median_spread_bps=statistics.median(spreads), option_contracts=len(spreads))
    return row


def sample(root: Path, symbols: list[str], now: pd.Timestamp, quote_for=yahoo_quote, chain_for=yahoo_near_chain) -> dict:
    """One snapshot of every instrument's share and near-the-money option spreads, appended to today's file."""
    if not in_sampling_window(now):
        return {"sampled": 0, "skipped": "outside regular trading hours"}
    path = Path(root) / SAMPLES / f"{now.tz_convert(NY):%Y-%m-%d}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    rows, failed = [], []
    for symbol in symbols:
        try:
            rows.append(sample_symbol(symbol, now, quote_for, chain_for))
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


# --- OCC options volume --------------------------------------------------------------------------

def parse_occ(text: str, symbol: str) -> dict | None:
    frame = pd.read_csv(io.StringIO(text), index_col=False)
    if frame.empty or "quantity" not in frame:
        return None
    standard = frame[frame["symbol"].astype(str).str.upper() == symbol.upper()]
    raw = int(standard["quantity"].sum())
    return {"all_series_sides": int(frame["quantity"].sum()), "standard_sides": raw, "one_sided_estimate": raw // 2}


def occ_volume(symbol: str, day: str, get=requests.get) -> dict | None:
    response = get(OCC_URL.format(day=day.replace("-", ""), symbol=symbol), headers=HEADERS, timeout=40)
    response.raise_for_status()
    return parse_occ(response.text, symbol)


def load_occ(root: Path) -> pd.DataFrame:
    path = Path(root) / OCC_FILE
    return pd.read_csv(path, dtype={"session_date": str}) if path.exists() else pd.DataFrame(
        columns=["session_date", "symbol", "all_series_sides", "standard_sides", "one_sided_estimate", "fetched_at"])


def update_occ(root: Path, symbols: list[str], days: list[str], get=requests.get, pause: float = 0.2) -> int:
    """Fetch OCC figures not yet saved; days OCC hasn't published (or no longer keeps) are retried later."""
    have = load_occ(root)
    known = set(zip(have["session_date"], have["symbol"]))
    added = []
    for symbol in symbols:
        for day in days:
            if (day, symbol) in known:
                continue
            try:
                figures = occ_volume(symbol, day, get)
            except Exception:
                continue
            if figures:
                added.append({"session_date": day, "symbol": symbol, **figures,
                              "fetched_at": pd.Timestamp.now(tz="UTC").isoformat(timespec="seconds")})
            time.sleep(pause)
    if added:
        path = Path(root) / OCC_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(added).to_csv(path, mode="a", header=not path.exists(), index=False, lineterminator="\n")
    return len(added)


# --- Daily records -------------------------------------------------------------------------------

def yahoo_daily_volume(symbol: str) -> dict[str, int]:
    import yfinance as yf
    frame = yf.Ticker(symbol).history(period="3mo", interval="1d", auto_adjust=False)
    return {f"{ts:%Y-%m-%d}": int(v) for ts, v in frame["Volume"].dropna().items()}


def day_record(symbol: str, day: str, samples: list[dict], share_volume: int | None, options_volume: int | None,
               now: pd.Timestamp, occ: dict | None = None) -> dict | None:
    mine = [s for s in samples if s.get("symbol") == symbol]
    shares = [s["share_spread_bps"] for s in mine if s.get("share_spread_bps") is not None]
    options = [s["option_median_spread_bps"] for s in mine if s.get("option_median_spread_bps") is not None]
    if not shares or share_volume is None:
        return None
    stamp = now.tz_convert("UTC").isoformat()
    return {"symbol": symbol, "session_date": day, "complete_session": len(shares) >= MIN_SAMPLES,
            "source": SOURCE, "source_timestamp": stamp, "available_at": stamp, "spread_basis": "midpoint",
            "metric_method": METHOD, "share_volume": int(share_volume),
            "share_median_spread_bps": round(statistics.median(shares), 4),
            "options_volume": int(options_volume) if options_volume is not None else None,
            "options_median_spread_bps": round(statistics.median(options), 4) if len(options) >= MIN_SAMPLES else None,
            "options_scope": SCOPE,
            "provenance": {"share_samples": len(shares), "option_samples": len(options),
                           "sample_times": [s["sampled_at"] for s in mine], "occ": occ}}


def update(root: Path, symbols: list[str], now: pd.Timestamp, get=requests.get, volume_for=yahoo_daily_volume,
           say=print, lookback: int = 20, pause: float = 0.2) -> dict:
    """After the close: fetch missing OCC days, then write each finished day's record once it is complete."""
    from liquidity_screen import _load, import_verified
    today = now.tz_convert(NY).tz_localize(None).normalize()
    finished = [d for d in equity_sessions(today - timedelta(days=45), today)
                if pd.Timestamp(f"{d:%Y-%m-%d} 16:15").tz_localize(NY) <= now][-lookback:]
    days = [f"{d:%Y-%m-%d}" for d in finished]
    fetched = update_occ(root, symbols, days, get, pause)
    occ = load_occ(root).drop_duplicates(["session_date", "symbol"]).set_index(["session_date", "symbol"])
    written = {k for k in _load(root, "snapshot")}
    records, waiting = [], 0
    volumes: dict[str, dict] = {}
    for position, day in enumerate(days):
        samples = load_samples(root, day)
        if not samples:
            continue
        for symbol in symbols:
            if (symbol, day) in written:
                continue
            key = (day, symbol)
            occ_row = {k: (v.item() if hasattr(v, "item") else v) for k, v in occ.loc[key].items()} if key in occ.index else None
            if occ_row is None and len(days) - position <= OCC_PATIENCE:
                waiting += 1
                continue
            if symbol not in volumes:
                try:
                    volumes[symbol] = volume_for(symbol)
                except Exception:
                    volumes[symbol] = {}
            record = day_record(symbol, day, samples, volumes[symbol].get(day),
                                occ_row["one_sided_estimate"] if occ_row else None, now, occ_row)
            if record:
                records.append(record)
    result = import_verified(root, records, journal="snapshot") if records else {"accepted": 0}
    say(f"Liquidity: {fetched} OCC day(s) fetched; {result['accepted']} day record(s) written to the snapshot "
        f"journal; {waiting} waiting for OCC.")
    return {"occ_fetched": fetched, "records": result["accepted"], "waiting_for_occ": waiting}
