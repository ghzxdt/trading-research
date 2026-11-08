"""Download the free data stage 1 needs, and cache it under data/raw/.

Sources (all free, no sign-up):
  - ETF prices ............ Yahoo Finance via the `yfinance` package (unofficial, but free)
  - VIX family ............ Cboe's public daily history files
  - Treasury yields ....... FRED (St. Louis Fed) public CSV download
  - Event dates ........... data/events/events.csv (BLS + Federal Reserve dates, kept in the repo)
  - Long history .......... SPY since 1993 and QQQ since 1999 (Yahoo), used only for risk numbers

Every download is saved to data/raw/ so a later run can work offline (--offline).
Each fetch also records how it went ("downloaded", "offline" or "failed" = fell back to the saved
copy), so the report can say when it was built from old data.
"""

from __future__ import annotations

import time
import io
import os
import shutil
import tempfile
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests

from validation import FLOAT_FORMAT, ValidationError, now_et, validate_etf_cache, validate_series

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
EVENTS_FILE = ROOT / "data" / "events" / "events.csv"

START = "2010-01-01"
LONG_START = "1993-01-01"  # SPY began trading Jan 1993; QQQ in Mar 1999
LONG_ETFS = ["SPY", "QQQ"]

# What we analyze and what we might trade.
ETFS = ["SPY", "QQQ", "IWM", "DIA", "RSP", "TQQQ", "SQQQ", "UPRO", "SPXU"]

CBOE_URL = "https://cdn.cboe.com/api/global/us_indices/daily_prices/{name}_History.csv"
VOL_INDEXES = ["VIX", "VIX9D", "VIX3M", "VVIX"]

FRED_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}"
RATES = ["DGS2", "DGS10"]

HEADERS = {"User-Agent": "index-research-stage1/0.1 (personal research script)"}


def _get(url: str, tries: int = 3) -> str:
    last = None
    for attempt in range(tries):
        try:
            r = requests.get(url, headers=HEADERS, timeout=60)
            r.raise_for_status()
            return r.text
        except requests.RequestException as e:  # network hiccup: wait and retry
            last = e
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"Could not download {url}: {last}")


def _cache(name: str) -> Path:
    RAW.mkdir(parents=True, exist_ok=True)
    return RAW / name


def _replace_cache(path: Path, content: str) -> None:
    """Only called after candidate validation; never truncate the last good file."""
    data = content.encode("utf-8")
    if path.exists() and path.read_bytes() == data:
        return
    fd, name = tempfile.mkstemp(prefix=path.stem + "_candidate_", suffix=path.suffix, dir=path.parent)
    candidate = Path(name)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        if path.exists():
            previous = path.with_name(path.stem + "_previous" + path.suffix)
            shutil.copy2(path, previous)
        os.replace(candidate, path)
    finally:
        candidate.unlink(missing_ok=True)


def _normalise_etfs(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        raise ValidationError("Yahoo returned no prices.")
    long = df.stack(level=0, future_stack=True).rename_axis(["date", "ticker"]).reset_index()
    long.columns = [str(c).lower() for c in long.columns]
    long = long.dropna(subset=["close"])
    long["date"] = pd.to_datetime(long["date"]).dt.tz_localize(None).dt.normalize()
    now = now_et()
    if (now.hour, now.minute) < (16, 30):
        long = long[long["date"] < now.tz_localize(None).normalize()]
    return long.sort_values(["date", "ticker"]).reset_index(drop=True)


def _fetch_etf_file(path: Path, required: list[str], start: str, offline: bool, status: dict):
    previous = pd.read_csv(path, parse_dates=["date"]) if path.exists() else None
    how = "offline" if offline else "downloaded"
    if not offline:
        import yfinance as yf
        error = None
        for attempt in range(3):
            try:
                candidate = _normalise_etfs(yf.download(required, start=start, auto_adjust=True,
                                            progress=False, group_by="ticker", threads=True))
                validate_etf_cache(candidate, required, previous)
                _replace_cache(path, candidate.to_csv(index=False, float_format=FLOAT_FORMAT, lineterminator="\n"))
                error = None
                break
            except Exception as e:
                error = e
                if attempt < 2:
                    time.sleep(3 * (attempt + 1))
        if error is not None:
            if previous is None:
                raise RuntimeError(f"Yahoo candidate rejected and no cache exists: {error}") from error
            print(f"  Yahoo candidate rejected; keeping the previous cache: {error}")
            how = "failed"
    if not path.exists():
        raise ValidationError(f"Required cached input missing: {path.name}")
    current = pd.read_csv(path, parse_dates=["date"])
    validate_etf_cache(current, required)
    _record(status, "ETF prices (Yahoo)", path, how)
    return {t: g.drop(columns="ticker").set_index("date").sort_index() for t, g in current.groupby("ticker")}


_RANK = {"downloaded": 0, "offline": 1, "failed": 2}


def _record(status: dict, source: str, path: Path, how: str) -> None:
    """Remember how a source was loaded. For multi-file sources, keep the worst case and oldest file."""
    saved = datetime.fromtimestamp(path.stat().st_mtime) if path.exists() else None
    prev = status.get(source)
    if prev is None or _RANK[how] > _RANK[prev["how"]]:
        status[source] = {"how": how, "saved": saved}
    elif saved and prev["saved"] and saved < prev["saved"]:
        prev["saved"] = saved


def fetch_etfs(offline: bool = False, status: dict | None = None) -> dict[str, pd.DataFrame]:
    """Daily open/high/low/close/volume, adjusted for splits and dividends."""
    status = {} if status is None else status
    return _fetch_etf_file(_cache("etfs.csv"), ETFS, START, offline, status)


def fetch_etfs_long(offline: bool = False, status: dict | None = None) -> dict[str, pd.DataFrame]:
    """SPY and QQQ from their first trading days, for risk numbers (worst days, gaps) that should
    include 2000-2002 and 2008. Kept separate from the main table, which starts in 2010."""
    status = {} if status is None else status
    return _fetch_etf_file(_cache("etfs_long.csv"), LONG_ETFS, LONG_START, offline, status)


def fetch_vol_indexes(offline: bool = False, status: dict | None = None) -> pd.DataFrame:
    """Daily closes for VIX, VIX9D, VIX3M and VVIX."""
    status = {} if status is None else status
    frames = []
    for name in VOL_INDEXES:
        path = _cache(f"{name}.csv")
        how = "offline" if offline else "downloaded"
        if not offline:
            try:
                content = _get(CBOE_URL.format(name=name))
                candidate = pd.read_csv(io.StringIO(content))
                candidate.columns = [c.strip().upper() for c in candidate.columns]
                col = "CLOSE" if "CLOSE" in candidate else name
                previous = pd.read_csv(path) if path.exists() else None
                if previous is not None:
                    previous.columns = [c.strip().upper() for c in previous.columns]
                validate_series(candidate, "DATE", col, previous, positive=True)
                _replace_cache(path, content)
            except (RuntimeError, ValueError, KeyError) as e:
                if not path.exists():
                    raise
                print(f"  {e}; using the cached copy.")
                how = "failed"
        _record(status, "VIX family (Cboe)", path, how)
        df = pd.read_csv(path)
        df.columns = [c.strip().upper() for c in df.columns]
        df["DATE"] = pd.to_datetime(df["DATE"], format="%m/%d/%Y")
        col = "CLOSE" if "CLOSE" in df.columns else name
        validate_series(df, "DATE", col, positive=True)
        frames.append(df.set_index("DATE")[col].rename(name.lower()))
    out = pd.concat(frames, axis=1, sort=True).sort_index()
    out.index.name = "date"
    return out


def fetch_rates(offline: bool = False, status: dict | None = None) -> pd.DataFrame:
    """2-year and 10-year Treasury yields (percent)."""
    status = {} if status is None else status
    frames = []
    for series in RATES:
        path = _cache(f"{series}.csv")
        how = "offline" if offline else "downloaded"
        if not offline:
            try:
                content = _get(FRED_URL.format(series=series))
                candidate = pd.read_csv(io.StringIO(content))
                candidate.columns = ["date", series]
                previous = pd.read_csv(path) if path.exists() else None
                if previous is not None:
                    previous.columns = ["date", series]
                validate_series(candidate, "date", series, previous, allow_missing=True)
                _replace_cache(path, content)
            except (RuntimeError, ValueError, KeyError) as e:
                if not path.exists():
                    raise
                print(f"  {e}; using the cached copy.")
                how = "failed"
        _record(status, "Treasury yields (FRED)", path, how)
        df = pd.read_csv(path)
        df.columns = ["date", series]
        validate_series(df, "date", series, allow_missing=True)
        df["date"] = pd.to_datetime(df["date"])
        df[series] = pd.to_numeric(df[series], errors="coerce")
        frames.append(df.set_index("date")[series].rename(series.lower()))
    return pd.concat(frames, axis=1, sort=True).sort_index()


def load_events() -> pd.DataFrame:
    ev = pd.read_csv(EVENTS_FILE, parse_dates=["date"])
    return ev


def fetch_all(offline: bool = False) -> dict:
    status: dict = {}
    print("Downloading ETF prices (Yahoo)..." if not offline else "Loading cached ETF prices...")
    etfs = fetch_etfs(offline, status)
    print("Downloading SPY/QQQ long history (Yahoo)..." if not offline else "Loading cached long history...")
    etfs_long = fetch_etfs_long(offline, status)
    print("Downloading VIX family (Cboe)..." if not offline else "Loading cached VIX family...")
    vol = fetch_vol_indexes(offline, status)
    print("Downloading Treasury yields (FRED)..." if not offline else "Loading cached yields...")
    rates = fetch_rates(offline, status)
    events = load_events()
    return {"etfs": etfs, "etfs_long": etfs_long, "vol": vol, "rates": rates, "events": events, "status": status}
