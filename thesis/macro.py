"""Rates, financial conditions and recession gauges from FRED (free, no key), plus a check of the VIX close.

Picked 2026-11-14 as context worth tracking for an index thesis (user: "lets add the other FRED data you feel is
worth tracking"). None of these is a signal: a gauge only enters the stance if the backtester tests it first as
a registered rule.

- Fed: effective fed funds rate (DFF) and the target range (DFEDTARL, DFEDTARU).
- Rates: 10-year minus 3-month Treasury (T10Y3M), 10-year breakeven inflation (T10YIE).
- Financial conditions: Chicago Fed NFCI (weekly, since 1971), St. Louis Fed Financial Stress Index (STLFSI4,
  weekly, since 1993).
- Recession gauge: the real-time Sahm rule (SAHMREALTIME, monthly).
- VIX close as FRED publishes it (VIXCLS), compared with the Cboe file the app uses, so the VIX does not rest on
  one copy. FRED posts it a day later, so it can't replace waiting for Cboe in the evening.

An online refresh downloads to data/raw/fred/<ID>.csv; a failed or implausible download keeps the saved copy.
Dates are the period each value describes; weekly and monthly values are published days to weeks later.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

from . import data

URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}"
HEADERS = {"User-Agent": "index-research-thesis/0.1 (personal research script)"}
FOLDER = Path("data/raw/fred")
# id -> (label, group, unit, plausible range, how to read it)
SERIES = {
    "DFF": ("Effective fed funds rate", "fed", "%", (0, 25), "The overnight rate the Fed steers."),
    "DFEDTARL": ("Fed target range, lower", "fed", "%", (0, 25), ""),
    "DFEDTARU": ("Fed target range, upper", "fed", "%", (0, 25), ""),
    "T10Y3M": ("10-year minus 3-month Treasury", "rates", "pts", (-6, 6),
               "Below zero (inverted) has come before most US recessions since the 1960s, often by a year or more, "
               "and has also stayed inverted for long stretches."),
    "T10YIE": ("10-year breakeven inflation", "rates", "%", (-3, 6),
               "Average inflation over 10 years implied by Treasury and TIPS prices."),
    "NFCI": ("Chicago Fed National Financial Conditions Index", "conditions", "", (-5, 15),
             "Zero is average since 1971; above zero is tighter than average, below zero looser."),
    "STLFSI4": ("St. Louis Fed Financial Stress Index", "conditions", "", (-5, 20),
                "Zero is normal; above zero is more market stress than average."),
    "SAHMREALTIME": ("Sahm rule (real time)", "recession", "pts", (-3, 15),
                     "The rise in the 3-month average unemployment rate over its low of the past year. 0.5 or more "
                     "has come near the start of past recessions, and has also been reached without one (2024)."),
    "VIXCLS": ("VIX close (FRED copy)", "check", "", (5, 100), ""),
}


def refresh(root: Path, get=requests.get) -> dict:
    folder = Path(root) / FOLDER
    folder.mkdir(parents=True, exist_ok=True)
    status = {}
    for series, (_, _, _, (low, high), _) in SERIES.items():
        stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        try:
            response = get(URL.format(series=series), headers=HEADERS, timeout=60)
            response.raise_for_status()
            temp = folder / f"{series}.tmp"
            temp.write_text(response.text, encoding="utf-8")
            values = data.fred(temp)
            if len(values) < 24 or (values < low).any() or (values > high).any():
                temp.unlink(missing_ok=True)
                raise ValueError(f"unexpected series ({len(values)} observations)")
            temp.replace(folder / f"{series}.csv")
            status[series] = {"ok": True, "observed_at": stamp, "last": f"{values.index[-1]:%Y-%m-%d}"}
        except Exception as exc:
            status[series] = {"ok": False, "attempted_at": stamp, "error": str(exc)[:200]}
    (folder / "status.json").write_text(json.dumps(status, indent=2), encoding="utf-8")
    return status


def _value_before(series: pd.Series, when: pd.Timestamp) -> float | None:
    earlier = series[series.index <= when]
    return float(earlier.iloc[-1]) if len(earlier) else None


def describe(series: pd.Series) -> dict | None:
    if series.empty:
        return None
    last_day, last = series.index[-1], float(series.iloc[-1])
    month, quarter = _value_before(series, last_day - pd.DateOffset(months=1)), _value_before(series, last_day - pd.DateOffset(months=3))
    return {"date": f"{last_day:%Y-%m-%d}", "value": last, "since": f"{series.index[0]:%Y-%m-%d}",
            "change_1m": last - month if month is not None else None,
            "change_3m": last - quarter if quarter is not None else None,
            "percentile": float((series <= last).mean())}


def vix_check(cboe: pd.Series, fred: pd.Series, days: int = 500) -> dict:
    """Cboe's VIX closes against FRED's copy over the recent overlap."""
    joined = pd.concat([cboe, fred], axis=1, keys=["cboe", "fred"]).dropna().iloc[-days:]
    if joined.empty:
        return {"status": "unavailable", "reason": "No overlapping VIX closes to compare yet."}
    diff = (joined["cboe"] - joined["fred"]).abs()
    off = diff[diff > 0.011]
    return {"status": "match" if off.empty else "differ", "compared": int(len(joined)),
            "from": f"{joined.index[0]:%Y-%m-%d}", "through": f"{joined.index[-1]:%Y-%m-%d}",
            "differences": int(len(off)), "largest": float(diff.max()),
            "examples": [f"{d:%Y-%m-%d}: Cboe {joined.loc[d, 'cboe']:.2f}, FRED {joined.loc[d, 'fred']:.2f}" for d in off.index[-5:]],
            "fred_missing_latest": [f"{d:%Y-%m-%d}" for d in cboe.index[cboe.index > joined.index[-1]][-3:]]}


def build(root: Path, now: pd.Timestamp) -> dict:
    folder = Path(root) / FOLDER
    loaded = {s: data.fred(folder / f"{s}.csv", now) for s in SERIES}
    if all(v.empty for v in loaded.values()):
        return {"status": "unavailable", "rows": [], "reason": "FRED series not downloaded yet; the next online refresh fetches them."}
    rows = []
    for series, (label, group, unit, _, read) in SERIES.items():
        if group in ("check",) or series in ("DFEDTARL", "DFEDTARU"):
            continue
        info = describe(loaded[series])
        rows.append({"series": series, "label": label, "group": group, "unit": unit, "read": read,
                     "status": "ok" if info else "unavailable", **(info or {})})
    low, high = describe(loaded["DFEDTARL"]), describe(loaded["DFEDTARU"])
    target = {"low": low["value"], "high": high["value"], "date": high["date"]} if low and high else None
    sahm = next((r for r in rows if r["series"] == "SAHMREALTIME" and r["status"] == "ok"), None)
    return {"status": "ok", "rows": rows, "target_range": target,
            "sahm_triggered": bool(sahm and sahm["value"] >= 0.5),
            "vix_check": vix_check(data.cboe(root, "VIX", now), loaded["VIXCLS"]),
            "note": "Context, not signals. Percentile: share of the series' own history at or below the latest value. "
                    "Dates are the period each value describes; weekly and monthly series are published later."}
