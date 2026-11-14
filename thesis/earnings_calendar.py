"""Earnings calendar: every large company reporting in the next two weeks, day by day.

Source: Nasdaq.com's public earnings calendar (Zacks data), one request per trading day. It lists each
company's report day, whether it reports before the open or after the close, its market value and the
consensus EPS forecast. This is a single source; the ten largest index holdings are also checked against Yahoo
in the mega-cap table (thesis/earnings.py), and a disagreement is flagged there.

Only companies worth at least MIN_CAP are kept, since a small company's report doesn't move SPY or QQQ.
An online refresh downloads to data/raw/earnings/calendar.json; offline builds only read it. A day whose
download fails keeps its last good copy, marked as such. Dates are scheduled dates and can change.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

from .data import NY
from .earnings import COMPANIES, HEADERS

URL = "https://api.nasdaq.com/api/calendar/earnings"
FILE = Path("data/raw/earnings/calendar.json")
MIN_CAP = 25e9
LARGE_CAP = 200e9
SESSIONS = 10
TIMING = {"time-after-hours": "after close", "time-pre-market": "before open"}


def _money(text) -> float | None:
    try:
        return float(str(text).replace("$", "").replace(",", "").replace("(", "-").replace(")", ""))
    except ValueError:
        return None


def nasdaq_day(day: str, get=requests.get) -> list[dict]:
    response = get(URL, params={"date": day}, headers=HEADERS, timeout=30)
    response.raise_for_status()
    rows = ((response.json() or {}).get("data") or {}).get("rows") or []
    out = []
    for row in rows:
        cap = _money(row.get("marketCap"))
        if not row.get("symbol") or cap is None or cap < MIN_CAP:
            continue
        out.append({"symbol": str(row["symbol"]), "name": str(row.get("name") or ""), "market_cap": cap,
                    "timing": TIMING.get(row.get("time"), "time not given"),
                    "eps_forecast": _money(row.get("epsForecast")) if row.get("epsForecast") else None,
                    "estimates": int(row["noOfEsts"]) if str(row.get("noOfEsts") or "").isdigit() else None,
                    "quarter": row.get("fiscalQuarterEnding")})
    return sorted(out, key=lambda r: -r["market_cap"])


def refresh(root: Path, now: pd.Timestamp | None = None, day_rows=nasdaq_day, pause: float = 0.3) -> dict:
    from validation import equity_sessions
    now = now if now is not None else pd.Timestamp.now(tz=NY)
    today = now.tz_convert(NY).normalize().tz_localize(None)
    path = Path(root) / FILE
    previous = (json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}).get("days") or {}
    days, failed = {}, []
    for session in equity_sessions(today, today + pd.Timedelta(days=21))[:SESSIONS]:
        day = f"{session:%Y-%m-%d}"
        try:
            days[day] = {"ok": True, "rows": day_rows(day)}
        except Exception as exc:  # keep the last good copy for that day, marked as such
            days[day] = {"ok": False, "rows": (previous.get(day) or {}).get("rows") or [], "error": str(exc)[:160]}
            failed.append(day)
        time.sleep(pause)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps({"fetched_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "days": days},
                               indent=1), encoding="utf-8")
    temp.replace(path)
    return {"days": len(days), "companies": sum(len(d["rows"]) for d in days.values()), "failed": failed}


def build(root: Path, now: pd.Timestamp) -> dict:
    path = Path(root) / FILE
    if not path.exists():
        return {"status": "unavailable", "days": [],
                "reason": "The earnings calendar has not been downloaded yet; the next online refresh fetches it."}
    saved = json.loads(path.read_text(encoding="utf-8"))
    today = f"{now.tz_convert(NY):%Y-%m-%d}"
    mega = {symbol for symbol, _ in COMPANIES}
    days = []
    for day in sorted(saved.get("days") or {}):
        if day < today:
            continue
        entry = saved["days"][day]
        rows = [{**r, "mega": r["symbol"] in mega, "large": r["market_cap"] >= LARGE_CAP} for r in entry.get("rows") or []]
        days.append({"date": day, "weekday": f"{pd.Timestamp(day):%a}", "ok": bool(entry.get("ok")), "rows": rows,
                     "largest": [r["symbol"] for r in rows if r["large"]]})
    return {"status": "ok", "fetched_utc": saved.get("fetched_utc"), "days": days,
            "companies": sum(len(d["rows"]) for d in days), "min_cap_billions": MIN_CAP / 1e9,
            "note": "Scheduled report days from Nasdaq.com (Zacks data), companies worth $25 billion or more. One "
                    "source: dates can change, and only the ten largest holdings are checked against Yahoo (table "
                    "below). The EPS figure is the consensus forecast Nasdaq shows, not this app's estimate."}
