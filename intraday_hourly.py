"""Hourly bars from Yahoo (free, no account) and the intraday base rates built from them.

Yahoo serves about 730 trading days (about 2.9 years) of one-hour bars for the regular session: 9:30, 10:30, ...
14:30 and a final 30-minute bar at 15:30 ET (12:30 is the last on an early-close day). Each refresh adds new bars
to data/intraday_hourly/<SYMBOL>.csv and keeps the old ones, so the history grows past Yahoo's window over time.
Prices are as traded (not dividend-adjusted), so a session's gap is measured against the previous session's last
hourly close.

Base rates, per session, for SPY, QQQ and IWM. Buckets were declared here on 2026-11-14 before looking at results:
- gap: the open against the previous close, in five buckets;
- gap filled: a gap up traded back down to the previous close during the session (a gap down, back up to it);
- first hour: share of the day's range made in the 9:30 bar, and whether the rest of the day (10:30 to the close)
  kept going the way the first hour went;
- first-hour range break: the day went above the first hour's high (or below its low) later, and whether it
  closed beyond it.
This is descriptive history at one-hour resolution: not the registered 15-minute opening-range rule, not forward
evidence, and not a signal. Bars carry no quotes, so nothing here says what a trade would have cost.

Alpaca (a free account with an API key) offers minute bars back to 2016 as far as known on 2026-11-14; it would
add finer resolution and a longer history if the user chooses to set it up later.
"""
from __future__ import annotations

import math
from pathlib import Path

import pandas as pd

NY = "America/New_York"
SYMBOLS = ("SPY", "QQQ", "IWM")
FOLDER = Path("data/intraday_hourly")
COLUMNS = ["timestamp", "open", "high", "low", "close", "volume"]
GAP_BUCKETS = ((-math.inf, -0.005, "Gap down more than 0.5%"), (-0.005, -0.002, "Gap down 0.2% to 0.5%"),
               (-0.002, 0.002, "Within 0.2%"), (0.002, 0.005, "Gap up 0.2% to 0.5%"),
               (0.005, math.inf, "Gap up more than 0.5%"))
FUTURE_FOR = {"SPY": "ES=F", "QQQ": "NQ=F"}


def yahoo_hourly(symbol: str) -> pd.DataFrame:
    import yfinance as yf
    frame = yf.download(symbol, period="730d", interval="1h", auto_adjust=False, prepost=False, progress=False)
    if frame is None or frame.empty:
        return pd.DataFrame(columns=COLUMNS)
    if isinstance(frame.columns, pd.MultiIndex):
        frame.columns = frame.columns.get_level_values(0)
    out = frame.rename(columns=str.lower)[["open", "high", "low", "close", "volume"]].dropna(subset=["open", "close"])
    out.index = pd.DatetimeIndex(out.index).tz_convert(NY)
    return out.rename_axis("timestamp").reset_index()


def load(root: Path, symbol: str) -> pd.DataFrame:
    path = Path(root) / FOLDER / f"{symbol}.csv"
    if not path.exists():
        return pd.DataFrame(columns=COLUMNS)
    frame = pd.read_csv(path)
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True).dt.tz_convert(NY)
    return frame


def refresh(root: Path, symbols=SYMBOLS, download=yahoo_hourly) -> dict:
    """Add the latest download to each saved file; on overlap the newer download wins. A failure keeps the file."""
    out = {}
    for symbol in symbols:
        try:
            new = download(symbol)
            if new.empty or len(new) < 50:
                raise ValueError("too few bars returned")
            new = new.copy()
            new["timestamp"] = pd.to_datetime(new["timestamp"], utc=True).dt.tz_convert(NY)
            old = load(root, symbol)
            merged = pd.concat([old, new[COLUMNS]]) if len(old) else new[COLUMNS]
            merged["timestamp"] = pd.to_datetime(merged["timestamp"], utc=True).dt.tz_convert(NY)
            merged = merged.drop_duplicates("timestamp", keep="last").sort_values("timestamp")
            path = Path(root) / FOLDER / f"{symbol}.csv"
            path.parent.mkdir(parents=True, exist_ok=True)
            temp = path.with_suffix(".tmp")
            merged.assign(timestamp=merged["timestamp"].map(lambda t: t.isoformat())).to_csv(temp, index=False)
            temp.replace(path)
            out[symbol] = f"{len(merged)} bars, {merged['timestamp'].dt.date.nunique()} sessions"
        except Exception as exc:
            out[symbol] = f"failed: {str(exc)[:100]}"
    return out


def gap_bucket(gap: float) -> str:
    return next(label for low, high, label in GAP_BUCKETS if low <= gap < high)


def sessions(frame: pd.DataFrame, before=None) -> pd.DataFrame:
    """One row per complete session (a 9:30 bar and at least 4 bars), with the measures above."""
    if frame.empty:
        return pd.DataFrame()
    frame = frame.sort_values("timestamp")
    if before is not None:
        frame = frame[frame["timestamp"] < before]
    frame = frame.assign(day=frame["timestamp"].dt.strftime("%Y-%m-%d"), hm=frame["timestamp"].dt.strftime("%H:%M"))
    rows, prior_close = [], None
    for day, bars in frame.groupby("day", sort=True):
        complete = len(bars) >= 4 and bars["hm"].iloc[0] == "09:30"
        if complete and prior_close:
            first = bars.iloc[0]
            later = bars.iloc[1:]
            open_, close = float(first["open"]), float(bars["close"].iloc[-1])
            high, low = float(bars["high"].max()), float(bars["low"].min())
            gap = open_ / prior_close - 1
            fh_high, fh_low = float(first["high"]), float(first["low"])
            rows.append({"session": day, "gap": gap, "bucket": gap_bucket(gap),
                         "filled": (low <= prior_close) if gap > 0 else (high >= prior_close) if gap < 0 else True,
                         "first_hour_share": (fh_high - fh_low) / (high - low) if high > low else None,
                         # the rest of the day (10:30 to the close) continued the first hour's direction; measured
                         # from the first hour's close so the first hour's own move doesn't count twice
                         "first_hour_holds": (float(first["close"]) - open_) * (close - float(first["close"])) > 0,
                         "broke_high": bool((later["high"] > fh_high).any()), "closed_above": close > fh_high,
                         "broke_low": bool((later["low"] < fh_low).any()), "closed_below": close < fh_low,
                         "day_move": close / prior_close - 1})
        prior_close = float(bars["close"].iloc[-1]) if len(bars) else prior_close
    return pd.DataFrame(rows)


def wilson(hits: int, n: int, z: float = 1.645) -> tuple[float, float] | None:
    """90% interval for a proportion (honest for small samples)."""
    if n == 0:
        return None
    p = hits / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return max(0.0, centre - half), min(1.0, centre + half)


def _share(column: pd.Series) -> dict:
    column = column.dropna().astype(bool)
    hits, n = int(column.sum()), int(len(column))
    interval = wilson(hits, n)
    return {"rate": hits / n if n else None, "low": interval[0] if interval else None,
            "high": interval[1] if interval else None, "n": n}


def table(days: pd.DataFrame) -> list[dict]:
    out = []
    for _, _, label in GAP_BUCKETS:
        mine = days[days["bucket"] == label]
        if mine.empty:
            out.append({"bucket": label, "sessions": 0})
            continue
        broke_high = mine[mine["broke_high"]]
        broke_low = mine[mine["broke_low"]]
        out.append({"bucket": label, "sessions": int(len(mine)),
                    "filled": _share(mine["filled"]) if label != "Within 0.2%" else None,
                    "first_hour_share": float(mine["first_hour_share"].median()),
                    "first_hour_holds": _share(mine["first_hour_holds"]),
                    "broke_high_closed_above": _share(broke_high["closed_above"]) if len(broke_high) else None,
                    "broke_low_closed_below": _share(broke_low["closed_below"]) if len(broke_low) else None,
                    "mean_day_move": float(mine["day_move"].mean())})
    return out


def build(root: Path, now: pd.Timestamp, futures_rows: list[dict] | None = None) -> dict:
    """Base rates per ETF from saved hourly bars known at `now`, with the bucket today's futures point to."""
    cutoff = now.tz_convert(NY)
    moves = {r.get("symbol"): r.get("change_since_4pm") for r in futures_rows or []}
    out = []
    for symbol in SYMBOLS:
        days = sessions(load(root, symbol), before=cutoff - pd.Timedelta(minutes=30))
        if days.empty:
            continue
        hint = moves.get(FUTURE_FOR.get(symbol))
        out.append({"symbol": symbol, "sessions": int(len(days)), "first": days["session"].iloc[0],
                    "last": days["session"].iloc[-1], "rows": table(days),
                    "futures_move": hint, "futures_bucket": gap_bucket(hint) if hint is not None else None})
    if not out:
        return {"status": "unavailable", "symbols": [],
                "reason": "No hourly bars saved yet; the evening collection downloads them from Yahoo."}
    return {"status": "ok", "symbols": out,
            "note": "Descriptive history from Yahoo's free hourly bars, regular session only (about 2.9 years at first, "
                    "growing as bars are added). Gap: the 9:30 open against the previous close. Filled: traded back "
                    "to the previous close the same day. First hour: the 9:30-10:30 bar. Ranges are 90% intervals; "
                    "neighbouring days are not fully independent, so treat them as rough. Not the registered "
                    "15-minute opening-range rule, not forward evidence, and bars carry no trading costs. Buckets "
                    "were declared before looking. The futures hint is the E-mini move since 4 PM, which is not the "
                    "ETF's opening gap."}
