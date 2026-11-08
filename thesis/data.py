"""Read-only loaders for the saved daily data the thesis uses, cut off at what was known at `now`."""
from __future__ import annotations

import io
from pathlib import Path

import pandas as pd

NY = "America/New_York"
CLOSE_KNOWN = pd.Timedelta(hours=16, minutes=15)  # a session's daily bar counts only after its close is final
OHLCV = ["open", "high", "low", "close", "volume"]


def last_known_session(now: pd.Timestamp) -> pd.Timestamp:
    """Latest calendar date whose daily close is known at `now` (a partial daytime bar is never used)."""
    local = now.tz_convert(NY)
    day = local.normalize().tz_localize(None)
    return day if local - local.normalize() >= CLOSE_KNOWN else day - pd.Timedelta(days=1)


def _etfs(path: Path) -> dict[str, pd.DataFrame]:
    if not path.exists():
        return {}
    table = pd.read_csv(path, parse_dates=["date"])
    out = {}
    for symbol, group in table.groupby("ticker"):
        frame = group.set_index("date")[OHLCV].astype(float).sort_index()
        out[str(symbol)] = frame[~frame.index.duplicated(keep="last")]
    return out


def etfs(root: Path, now: pd.Timestamp) -> dict[str, pd.DataFrame]:
    """Longest saved daily history per ETF (SPY since 1993, QQQ since 1999, the rest since 2010)."""
    raw = Path(root) / "data" / "raw"
    short, long = _etfs(raw / "etfs.csv"), _etfs(raw / "etfs_long.csv")
    cutoff = last_known_session(now)
    out = {}
    for symbol in sorted(set(short) | set(long)):
        a, b = long.get(symbol), short.get(symbol)
        frame = a if b is None or (a is not None and len(a) >= len(b)) else b
        frame = frame[frame.index <= cutoff]
        if len(frame):
            out[symbol] = frame
    return out


def cboe(root: Path, name: str, now: pd.Timestamp) -> pd.Series:
    path = Path(root) / "data" / "raw" / f"{name}.csv"
    if not path.exists():
        return pd.Series(dtype=float)
    frame = pd.read_csv(path)
    frame.columns = [c.strip().upper() for c in frame.columns]
    series = pd.Series(pd.to_numeric(frame["CLOSE"], errors="coerce").to_numpy(),
                       index=pd.to_datetime(frame["DATE"], format="%m/%d/%Y")).dropna().sort_index()
    series = series[~series.index.duplicated(keep="last")]
    return series[series.index <= last_known_session(now)]


def fred(path: Path, now: pd.Timestamp | None = None) -> pd.Series:
    """A FRED CSV (date, value); FRED marks missing days with '.'."""
    if not Path(path).exists():
        return pd.Series(dtype=float)
    frame = pd.read_csv(io.StringIO(Path(path).read_text(encoding="utf-8")))
    frame.columns = ["date", "value"]
    series = pd.Series(pd.to_numeric(frame["value"], errors="coerce").to_numpy(),
                       index=pd.to_datetime(frame["date"])).dropna().sort_index()
    series = series[~series.index.duplicated(keep="last")]
    # FRED dates an observation by the day it describes and publishes it a day or more later, so a replay at
    # the close of day D uses values through D-1 at most.
    return series if now is None else series[series.index < last_known_session(now)]
