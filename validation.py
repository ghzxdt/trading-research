"""Shared input validation, US equity-session clock, and build provenance.

Passing these checks establishes structural integrity, not vendor truth or an edge.
The session calendar includes regular NYSE holidays and published exceptional
closures through 2026. It deliberately does not infer exchange hours for perps.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

NY = "America/New_York"
FLOAT_FORMAT = "%.17g"
EXCEPTIONAL_CLOSURES = {"1994-04-27", "2001-09-11", "2001-09-12", "2001-09-13", "2001-09-14",
                        "2004-06-11", "2007-01-02", "2012-10-29", "2012-10-30", "2018-12-05", "2025-01-09"}


class ValidationError(ValueError):
    pass


def output_dir(root: Path) -> Path:
    return Path(os.environ.get("APP_OUTPUT_DIR", str(root / "output"))).resolve()


def now_et() -> pd.Timestamp:
    value = os.environ.get("APP_AS_OF")
    t = pd.Timestamp(value) if value else pd.Timestamp.now(tz=NY)
    return t.tz_localize(NY) if t.tzinfo is None else t.tz_convert(NY)


def _easter(year: int) -> pd.Timestamp:
    # Gregorian computus; Good Friday is two days earlier.
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    n = h + l - 7 * m + 114
    return pd.Timestamp(year=year, month=n // 31, day=n % 31 + 1)


def _holidays(year: int) -> set[pd.Timestamp]:
    def fixed(month, day):
        t = pd.Timestamp(year=year, month=month, day=day)
        return t + pd.Timedelta(days=1 if t.day_of_week == 6 else -1 if t.day_of_week == 5 else 0)

    def nth(month, weekday, n):
        t = pd.Timestamp(year=year, month=month, day=1)
        return t + pd.Timedelta(days=(weekday - t.day_of_week) % 7 + 7 * (n - 1))

    ny = pd.Timestamp(year=year, month=1, day=1)
    # NYSE does not observe Saturday New Year's Day on the preceding Friday.
    result = {ny + pd.Timedelta(days=1 if ny.day_of_week == 6 else 0), nth(2, 0, 3),
              _easter(year) - pd.Timedelta(days=2),
              pd.Timestamp(year=year, month=5, day=31) - pd.Timedelta(days=pd.Timestamp(year=year, month=5, day=31).day_of_week),
              fixed(7, 4), nth(9, 0, 1), nth(11, 3, 4), fixed(12, 25)}
    if year >= 1998:
        result.add(nth(1, 0, 3))
    if year >= 2022:
        result.add(fixed(6, 19))
    result.update(pd.Timestamp(d) for d in EXCEPTIONAL_CLOSURES if d.startswith(str(year)))
    return result


def equity_sessions(start, end) -> pd.DatetimeIndex:
    start, end = pd.Timestamp(start).normalize().tz_localize(None), pd.Timestamp(end).normalize().tz_localize(None)
    if end < start:
        return pd.DatetimeIndex([])
    holidays = set().union(*(_holidays(y) for y in range(start.year, end.year + 1)))
    return pd.DatetimeIndex([d for d in pd.date_range(start, end, freq="B") if d not in holidays])


def expected_session(now=None, *, publication_hour=16, publication_minute=30) -> pd.Timestamp:
    t = pd.Timestamp(now) if now is not None else now_et()
    t = t.tz_localize(NY) if t.tzinfo is None else t.tz_convert(NY)
    end = t.tz_localize(None).normalize()
    if (t.hour, t.minute) < (publication_hour, publication_minute):
        end -= pd.Timedelta(days=1)
    return equity_sessions(end - pd.Timedelta(days=14), end)[-1]


def freshness(last, *, kind="equity", now=None) -> dict:
    t = pd.Timestamp(now) if now is not None else now_et()
    t = t.tz_localize(NY) if t.tzinfo is None else t.tz_convert(NY)
    if kind == "snapshot":
        if last is None or pd.isna(last):
            return {"ok": False, "last": None, "expected": str(t), "lag_sessions": None, "reason": "No snapshot timestamp."}
        stamp = pd.Timestamp(last)
        stamp = stamp.tz_localize("UTC") if stamp.tzinfo is None else stamp.tz_convert("UTC")
        age = (t.tz_convert("UTC") - stamp).total_seconds()
        ok = -300 <= age <= 3600
        return {"ok": ok, "last": stamp.isoformat(), "expected": t.isoformat(), "lag_sessions": None,
                "reason": f"Snapshot age {age / 3600:.1f} hours; live use requires age <= 1 hour."}
    expected = expected_session(t, publication_hour=20 if kind == "gex" else 16,
                                publication_minute=0 if kind == "gex" else 30)
    if kind == "rates":
        expected = equity_sessions(expected - pd.Timedelta(days=14), expected)[-2]
    if last is None or pd.isna(last):
        return {"ok": False, "last": None, "expected": f"{expected:%Y-%m-%d}", "lag_sessions": None, "reason": "No valid observation."}
    last = pd.Timestamp(last).tz_localize(None).normalize()
    lag = max(0, len(equity_sessions(last, expected)) - 1)
    future = last > t.tz_localize(None).normalize()
    return {"ok": last >= expected and not future, "last": f"{last:%Y-%m-%d}", "expected": f"{expected:%Y-%m-%d}",
            "lag_sessions": lag, "reason": f"Through {last:%Y-%m-%d}; expected {expected:%Y-%m-%d}" + ("; future-dated input." if future else f" ({lag} sessions behind).")}


def validate_etf_cache(frame: pd.DataFrame, required: list[str], previous: pd.DataFrame | None = None) -> None:
    needed = {"date", "ticker", "open", "high", "low", "close", "volume"}
    if not needed <= set(frame):
        raise ValidationError(f"ETF cache missing columns: {sorted(needed - set(frame))}")
    d = frame.copy()
    d["date"] = pd.to_datetime(d["date"], errors="coerce").dt.normalize()
    if d.empty or d["date"].isna().any() or d.duplicated(["date", "ticker"]).any():
        raise ValidationError("ETF cache is empty or contains invalid/duplicate ticker dates.")
    absent = set(required) - set(d["ticker"])
    if absent:
        raise ValidationError(f"ETF download incomplete; missing {sorted(absent)}")
    numeric = d[["open", "high", "low", "close", "volume"]].apply(pd.to_numeric, errors="coerce")
    if not np.isfinite(numeric.to_numpy()).all() or (numeric[["open", "high", "low", "close"]] <= 0).any().any() or (numeric["volume"] < 0).any():
        raise ValidationError("ETF cache has missing, nonfinite, nonpositive prices, or negative volume.")
    if ((numeric["high"] * 1.0005 < numeric[["open", "close", "low"]].max(axis=1)) |
        (numeric["low"] * .9995 > numeric[["open", "close", "high"]].min(axis=1))).any():
        raise ValidationError("ETF OHLC range is inconsistent (0.05% rounding tolerance).")
    reference_last = d.loc[d["ticker"] == "SPY", "date"].max() if "SPY" in required else d["date"].max()
    if reference_last > now_et().tz_localize(None).normalize():
        raise ValidationError("ETF cache contains future-dated observations.")
    for tk in required:
        dates = pd.DatetimeIndex(d.loc[d["ticker"] == tk, "date"]).sort_values()
        if dates[-1] != reference_last:
            raise ValidationError(f"{tk} ends {dates[-1].date()}, inconsistent with SPY {reference_last.date()}.")
        expected = equity_sessions(dates[0], dates[-1])
        if not dates.equals(expected):
            missing, unexpected = expected.difference(dates), dates.difference(expected)
            raise ValidationError(f"{tk} calendar gaps/unexpected sessions: missing {list(missing[:5])}; unexpected {list(unexpected[:5])}.")
        if previous is not None:
            old = previous.loc[previous["ticker"] == tk, "date"]
            if len(old) and (dates[0] > pd.to_datetime(old).min() or dates[-1] < pd.to_datetime(old).max() or len(dates) < len(old)):
                raise ValidationError(f"{tk} candidate loses cached history.")


def validate_series(frame: pd.DataFrame, date_column: str, value_column: str, previous: pd.DataFrame | None = None,
                    *, allow_missing=False, positive=False) -> None:
    if not {date_column, value_column} <= set(frame):
        raise ValidationError(f"Series missing {date_column}/{value_column} columns.")
    dates = pd.to_datetime(frame[date_column], errors="coerce")
    values = pd.to_numeric(frame[value_column], errors="coerce")
    if frame.empty or dates.isna().any() or dates.duplicated().any() or not dates.is_monotonic_increasing:
        raise ValidationError("Series is empty or has invalid/duplicate/unordered dates.")
    if not values.notna().any() or (not allow_missing and values.isna().any()) or np.isinf(values.dropna()).any() or (positive and (values.dropna() <= 0).any()):
        raise ValidationError("Series has invalid numeric values.")
    if allow_missing and values.notna().mean() < .75:
        raise ValidationError("Series has less than 75% numeric coverage.")
    if previous is not None and len(previous):
        old_dates = pd.to_datetime(previous[date_column])
        if dates.min() > old_dates.min() or dates.max() < old_dates.max() or len(frame) < len(previous):
            raise ValidationError("Candidate series loses cached history.")
        old_values = pd.to_numeric(previous[value_column], errors="coerce")
        if not pd.DatetimeIndex(old_dates[old_values.notna()]).difference(pd.DatetimeIndex(dates[values.notna()])).empty:
            raise ValidationError("Candidate replaces previously numeric observations with missing values.")


def validate_daily_table(t: pd.DataFrame) -> None:
    if t.empty or not t.index.is_unique or not t.index.is_monotonic_increasing:
        raise ValidationError("Daily table is empty, duplicated or unordered.")
    required = ["SPY", "QQQ", "IWM", "DIA", "RSP", "TQQQ", "SQQQ", "UPRO", "SPXU"]
    for tk in required:
        k = tk.lower()
        for field in ("open", "high", "low", "close", "ret"):
            if f"{k}_{field}" not in t:
                raise ValidationError(f"Daily table missing {tk} {field}.")
        if pd.isna(t[f"{k}_close"].iloc[-1]):
            raise ValidationError(f"Latest {tk} close missing.")
    if not t.index.equals(equity_sessions(t.index[0], t.index[-1])):
        raise ValidationError("Daily table does not match the US equity session calendar.")


def input_manifest(root: Path) -> dict:
    paths = sorted(p for p in (root / "data").rglob("*") if p.is_file() and "previous" not in p.stem.lower())
    return {p.relative_to(root).as_posix(): {"sha256": hashlib.sha256(p.read_bytes()).hexdigest(), "bytes": p.stat().st_size} for p in paths}


def write_component_manifest(component: str, out: Path, metadata: dict | None = None) -> None:
    out.mkdir(parents=True, exist_ok=True)
    content = {"component": component, "run_id": os.environ.get("APP_RUN_ID", "standalone"),
               "as_of": now_et().isoformat(), "build_time": os.environ.get("APP_BUILD_TIME"), **(metadata or {})}
    (out / f"manifest_{component}.json").write_text(json.dumps(content, indent=2, default=str, sort_keys=True), encoding="utf-8")
