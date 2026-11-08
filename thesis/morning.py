"""Morning view: what moved since the 4 PM close, and the inflation expectation going into CPI.

Reads the market snapshots the scheduled task records (8:00 AM and 3:05 PM Central):
- data/futures/futures_quotes.csv: S&P 500 and Nasdaq-100 E-mini futures (Yahoo, CME quotes), change since 4 PM.
- data/macro/inflation_nowcast.csv: the Cleveland Fed's daily CPI nowcasts (and actuals once released).
No Kalshi data is shown in the thesis (user, 2026-11-08); the snapshots still record it for later use.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from .data import NY

FUTURES = Path("data/futures/futures_quotes.csv")
NOWCAST = Path("data/macro/inflation_nowcast.csv")


def _read(path: Path, now) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    frame = pd.read_csv(path)
    if frame.empty or "snapshot_utc" not in frame:
        return pd.DataFrame()
    frame["snapshot_utc"] = pd.to_datetime(frame["snapshot_utc"], utc=True, errors="coerce")
    return frame[frame["snapshot_utc"] <= now.tz_convert("UTC")].dropna(subset=["snapshot_utc"])


def futures(root: Path, now) -> dict:
    frame = _read(Path(root) / FUTURES, now)
    if frame.empty:
        return {"status": "unavailable", "rows": [],
                "reason": "No futures snapshot yet. The scheduled market snapshot records one at 8:00 AM Central "
                          "(9:00 AM ET) and 3:05 PM Central on weekdays."}
    latest = frame[frame["snapshot_utc"] == frame["snapshot_utc"].max()]
    taken = latest["snapshot_utc"].iloc[0].tz_convert(NY)
    rows = [{"symbol": r["symbol"], "name": r.get("name"), "last_price": r.get("last_price"),
             "last_bar_et": r.get("last_bar_et"), "delay_min": r.get("delay_min"),
             "ref_4pm_price": r.get("ref_4pm_price"),
             "change_since_4pm": None if pd.isna(r.get("change_since_4pm_pct")) else float(r["change_since_4pm_pct"]) / 100}
            for r in latest.to_dict("records")]
    age = (now.tz_convert(NY) - taken).total_seconds() / 3600
    return {"status": "ok" if age < 16 else "stale", "snapshot_et": f"{taken:%Y-%m-%d %H:%M}", "slot": latest["slot"].iloc[0],
            "age_hours": age, "rows": rows,
            "note": "Yahoo futures quotes can be delayed (delay shown). The change is from the 4:00 PM ET bar."}


def nowcast(root: Path, now) -> dict:
    frame = _read(Path(root) / NOWCAST, now)
    if frame.empty:
        return {"status": "unavailable", "rows": [],
                "reason": "No Cleveland Fed nowcast saved yet; the 3:05 PM Central snapshot records it on weekdays."}
    latest = frame[frame["snapshot_utc"] == frame["snapshot_utc"].max()]
    rows = [{"target_month": r["target_month"], "series": r["series"], "value_mom_pct": r["value_mom_pct"],
             "as_of": r.get("as_of")} for r in latest.sort_values(["target_month", "series"]).to_dict("records")]
    return {"status": "ok", "snapshot_et": f"{latest['snapshot_utc'].iloc[0].tz_convert(NY):%Y-%m-%d %H:%M}", "rows": rows,
            "note": "Month-over-month % change nowcasts from the Cleveland Fed. A nowcast is a model estimate, not "
                    "the market consensus; the official consensus is not available for free."}


def mode(now) -> dict:
    local = now.tz_convert(NY)
    minutes = local.hour * 60 + local.minute
    weekday = local.weekday() < 5
    if not weekday:
        return {"mode": "weekend", "label": "Weekend view", "detail": "Markets are closed; the view is as of the last close."}
    if minutes < 9 * 60 + 30:
        return {"mode": "morning", "label": "Morning view", "detail": "Before the 9:30 AM ET open: last close plus overnight moves."}
    if minutes < 16 * 60 + 15:
        return {"mode": "session", "label": "Market open", "detail": "During the session the daily view stays at the last close; the Intraday tab is live."}
    return {"mode": "evening", "label": "Evening view", "detail": "After the close: today's close is in the view."}


def build(root: Path, now) -> dict:
    return {**mode(now), "futures": futures(root, now), "nowcast": nowcast(root, now)}
