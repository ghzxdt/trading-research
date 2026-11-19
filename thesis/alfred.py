"""First-release values and the official release schedule, from FRED / ALFRED (needs the user's free API key).

Why: jobs and CPI numbers are revised for months. On release morning the market reacted to the first number
announced, so a history built from today's revised figures has look-ahead. ALFRED keeps every vintage; this reads
all of them for five series and reconstructs, for each month:
- the release date (the day the month first appeared),
- the headline as first announced: the new month against the previous month *as it stood that day*,
- the same change as it stands now, and the revision between them.
It also reads FRED's official release dates for the Employment Situation and CPI, and checks the app's own event
calendar (data/events/events.csv) against them.

Key: the environment variable FRED_API_KEY, or the file .secrets/fred_api_key.txt (git-ignored). The key is never
logged or saved anywhere else; error messages have it removed. Without a key everything here is "no_key".
An online refresh downloads to data/raw/releases/alfred.json; offline builds only read it, and a replay only uses
vintages published by the replayed moment.
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

from .data import NY

API = "https://api.stlouisfed.org/fred"
KEY_FILE = Path(".secrets/fred_api_key.txt")
FILE = Path("data/raw/releases/alfred.json")
# name -> (FRED series, label, kind): "level_change" headline is new level minus previous level (in thousands for
# payrolls); "pct_change" is the month-over-month % change; "level" is the value itself.
SERIES = {"payrolls": ("PAYEMS", "Nonfarm payrolls", "level_change"),
          "unemployment": ("UNRATE", "Unemployment rate", "level"),
          "hourly_earnings": ("CES0500000003", "Average hourly earnings", "pct_change"),
          "cpi": ("CPIAUCSL", "CPI", "pct_change"),
          "core_cpi": ("CPILFESL", "Core CPI", "pct_change")}
RELEASES = {"jobs_report": (50, "Employment Situation"), "cpi": (10, "Consumer Price Index")}
START = "2014-01-01"


def api_key(root: Path) -> str | None:
    key = os.environ.get("FRED_API_KEY") or ""
    if not key:
        try:
            key = (Path(root) / KEY_FILE).read_text(encoding="utf-8-sig").strip()
        except OSError:
            key = ""
    key = key.strip().strip('"').strip()
    return key if len(key) == 32 and key.isalnum() else None


def _get(path: str, params: dict, key: str, get=requests.get) -> dict:
    try:
        response = get(f"{API}/{path}", params={**params, "api_key": key, "file_type": "json"}, timeout=40)
        response.raise_for_status()
        return response.json()
    except Exception as exc:  # requests puts the URL, key included, into its messages
        raise RuntimeError(str(exc).replace(key, "***")) from None


def vintages(series: str, key: str, get=requests.get) -> list[dict]:
    payload = _get("series/observations", {"series_id": series, "observation_start": START,
                                           "realtime_start": "2015-01-01", "realtime_end": "9999-12-31",
                                           "output_type": 1}, key, get)
    out = []
    for row in payload.get("observations") or []:
        try:
            out.append({"date": row["date"], "start": row["realtime_start"], "end": row["realtime_end"],
                        "value": float(row["value"])})
        except (KeyError, TypeError, ValueError):
            continue  # FRED marks a missing value with "."
    return out


def release_dates(release_id: int, key: str, today: str, get=requests.get) -> list[str]:
    payload = _get("release/dates", {"release_id": release_id, "realtime_start": today, "realtime_end": "9999-12-31",
                                     "include_release_dates_with_no_data": "true", "sort_order": "asc", "limit": 20},
                   key, get)
    return [d["date"] for d in payload.get("release_dates") or [] if d.get("date")]


def refresh(root: Path, key: str | None = None, get=requests.get, pause: float = 0.6) -> dict:
    key = key or api_key(root)
    if not key:
        return {"status": "no_key"}
    path = Path(root) / FILE
    saved = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    status, today = {}, f"{pd.Timestamp.now(tz=NY):%Y-%m-%d}"
    for name, (series, _, _) in SERIES.items():
        try:
            rows = vintages(series, key, get)
            if not rows:
                raise ValueError("no observations")
            saved.setdefault("series", {})[name] = rows
            status[name] = len(rows)
        except Exception as exc:  # keep the last good copy
            status[name] = f"failed: {str(exc)[:120]}"
        time.sleep(pause)
    for name, (release_id, _) in RELEASES.items():
        try:
            saved.setdefault("schedule", {})[name] = release_dates(release_id, key, today, get)
            status[f"{name}_dates"] = len(saved["schedule"][name])
        except Exception as exc:
            status[f"{name}_dates"] = f"failed: {str(exc)[:120]}"
        time.sleep(pause)
    saved["fetched_utc"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(saved), encoding="utf-8")
    temp.replace(path)
    return status


def _as_of(rows: list[dict], day: str) -> dict[str, float]:
    """Each observation's value as it stood on `day` (vintage dates are inclusive)."""
    out = {}
    for r in rows:
        if r["start"] <= day <= r["end"]:
            out[r["date"]] = r["value"]
    return out


RELEASE_TIME = pd.Timedelta(hours=8, minutes=30)  # BLS and the jobless-claims report publish at 8:30 AM ET


def known_day(now: pd.Timestamp) -> str:
    """The newest vintage date known at `now`: a vintage dated today exists only from 8:30 AM ET, when these
    releases come out (review A4, 2026-11-18; a replay at 8:00 AM used to show the 8:30 numbers)."""
    local = now.tz_convert(NY)
    day = local.normalize()
    return f"{day if local - day >= RELEASE_TIME else day - pd.Timedelta(days=1):%Y-%m-%d}"


def history(rows: list[dict], kind: str, today: str) -> list[dict]:
    """One row per month: its release date, the headline as first announced, as it stands now, and the revision."""
    rows = [r for r in rows if r["start"] <= today]
    first_seen: dict[str, str] = {}
    for r in rows:
        if r["date"] not in first_seen or r["start"] < first_seen[r["date"]]:
            first_seen[r["date"]] = r["start"]
    now_values = _as_of(rows, today)
    out = []
    for month in sorted(first_seen):
        released = first_seen[month]
        then = _as_of(rows, released)
        prior = f"{pd.Timestamp(month) - pd.DateOffset(months=1):%Y-%m-%d}"
        if month not in then or (kind != "level" and prior not in then):
            continue
        if kind == "level":
            first, current = then[month], now_values.get(month)
        elif kind == "level_change":
            first = then[month] - then[prior]
            current = now_values[month] - now_values[prior] if month in now_values and prior in now_values else None
        else:
            first = then[month] / then[prior] - 1
            current = now_values[month] / now_values[prior] - 1 if month in now_values and prior in now_values else None
        out.append({"month": month[:7], "released": released, "first": first, "current": current,
                    "revision": current - first if current is not None else None})
    # The first months in the window only have a "first release" if they appeared after realtime_start.
    return [r for r in out if r["released"] > "2015-01-01"]


def calendar_check(root: Path, schedule: dict, today: str) -> list[dict]:
    """Official upcoming dates against the app's event calendar."""
    path = Path(root) / "data" / "events" / "events.csv"
    mine = pd.read_csv(path, dtype=str).fillna("") if path.exists() else pd.DataFrame(columns=["date", "event"])
    out = []
    for event, dates in (schedule or {}).items():
        official = [d for d in dates if d >= today][:3]
        if not official:
            continue
        horizon = official[-1]
        listed = sorted(d for d in mine.loc[mine["event"] == event, "date"] if today <= d <= horizon)
        out.append({"event": event, "label": RELEASES[event][1], "official": official,
                    "missing_in_app": [d for d in official if d not in listed],
                    "extra_in_app": [d for d in listed if d not in official]})
    return out


def build(root: Path, now: pd.Timestamp) -> dict:
    has_key = api_key(root) is not None
    path = Path(root) / FILE
    if not path.exists():
        return {"status": "no_key" if not has_key else "unavailable", "rows": [], "history": {}, "schedule": [],
                "reason": "Add your free FRED API key to .secrets\\fred_api_key.txt; the next online refresh then "
                          "downloads first-release values." if not has_key else
                          "First-release values have not been downloaded yet; the next online refresh fetches them."}
    saved = json.loads(path.read_text(encoding="utf-8"))
    today = known_day(now)
    rows, hist = [], {}
    for name, (_, label, kind) in SERIES.items():
        months = history((saved.get("series") or {}).get(name) or [], kind, today)
        if not months:
            continue
        hist[name] = {"label": label, "kind": kind, "months": months[-12:]}
        latest = months[-1]
        revised = [m["revision"] for m in months[-36:-2] if m["revision"] is not None]
        rows.append({"name": label, "kind": kind, "month": latest["month"], "released": latest["released"],
                     "first": latest["first"], "current": latest["current"],
                     "typical_revision": float(pd.Series(revised).abs().median()) if revised else None,
                     "revised_months": len(revised)})
    return {"status": "ok" if rows else "unavailable", "rows": rows, "history": hist,
            "schedule": calendar_check(root, saved.get("schedule"), today), "fetched_utc": saved.get("fetched_utc"),
            "note": "First announced: the headline on release day, from FRED's vintage archive (ALFRED). Now: the same "
                    "month as revised since. Typical revision: the median absolute change between the two over the "
                    "previous three years, excluding the two newest months, which are still being revised. No "
                    "expectation is available for free, so no surprise is computed."}
