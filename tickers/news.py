"""News for the Tickers tab: headlines and links only (no article text).

Sources:
  - Yahoo Finance headlines per ticker, through the yfinance package (the same unofficial source
    the app already uses for prices).
  - The Federal Reserve's official press-release RSS feed (published for feed readers).
  - The app's own events calendar (jobs, CPI, Fed dates) plus options expiration and month-end.
Saved under data/raw/news/ so an offline run still shows the last headlines.
"""

from __future__ import annotations

import json
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw" / "news"
FED_RSS = "https://www.federalreserve.gov/feeds/press_all.xml"
HEADERS = {"User-Agent": "index-research-news/0.1 (personal research script)"}
NY = "America/New_York"


def _safe_url(u) -> str:
    u = str(u or "")
    return u if u.startswith(("https://", "http://")) else ""


def _cached(name: str, fetch, offline: bool, status: dict, label: str):
    RAW.mkdir(parents=True, exist_ok=True)
    path = RAW / name
    how = "offline" if offline else "downloaded"
    if not offline:
        try:
            path.write_text(json.dumps(fetch()), encoding="utf-8")
        except Exception as e:  # news is optional: never fail the build over it
            print(f"  {label}: {e}; using the saved copy." if path.exists() else f"  {label}: {e}.")
            how = "failed"
    status[label] = {"how": how if path.exists() else "missing",
                     "saved": datetime.fromtimestamp(path.stat().st_mtime) if path.exists() else None}
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []


def _yahoo(ticker: str) -> list[dict]:
    import yfinance as yf

    out = []
    for item in (yf.Ticker(ticker).news or [])[:20]:
        c = item.get("content", item) or {}
        url = _safe_url(((c.get("canonicalUrl") or {}).get("url")) or ((c.get("clickThroughUrl") or {}).get("url")))
        title = str(c.get("title") or "").strip()
        if not title or not url:
            continue
        out.append({"title": title, "url": url, "publisher": str((c.get("provider") or {}).get("displayName") or ""),
                    "time": str(c.get("pubDate") or c.get("displayTime") or "")})
    return out


def _fed() -> list[dict]:
    r = requests.get(FED_RSS, headers=HEADERS, timeout=30)
    r.raise_for_status()
    root = ET.fromstring(r.content)
    out = []
    for it in root.iter("item"):
        title = (it.findtext("title") or "").strip()
        url = _safe_url((it.findtext("link") or "").strip())
        when = it.findtext("pubDate") or ""
        try:
            when = parsedate_to_datetime(when).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        except (TypeError, ValueError):
            when = ""
        if title and url:
            out.append({"title": title, "url": url, "publisher": "Federal Reserve Board", "time": when})
    return out[:12]


def fetch(tickers: list[str], offline: bool = False) -> dict:
    status: dict = {}
    per = {}
    for t in tickers:
        per[t] = _cached(f"yahoo_{t}.json", lambda t=t: _yahoo(t), offline, status, f"Yahoo headlines: {t}")
        if not offline:
            time.sleep(0.3)
    fed = _cached("fed_press.json", _fed, offline, status, "Federal Reserve press releases")
    return {"tickers": per, "fed": fed, "status": status}


def when_et(iso: str) -> str:
    try:
        t = pd.Timestamp(iso)
        t = (t.tz_localize("UTC") if t.tzinfo is None else t).tz_convert(NY)
    except (ValueError, TypeError):
        return ""
    return f"{t:%b} {t.day}, {t:%I:%M %p}".replace(" 0", " ") + " ET"


def calendar(events: pd.DataFrame, last_day: pd.Timestamp, days: int = 45) -> list[dict]:
    """Upcoming scheduled events: the events file, plus monthly options expiration and month-end."""
    end = last_day + pd.Timedelta(days=days)
    names = {"jobs_report": "Jobs report (8:30 am)", "cpi": "Inflation report, CPI (8:30 am)", "fed_decision": "Fed decision (2:00 pm)"}
    out = []
    ev = events[(events["date"] > last_day) & (events["date"] <= end)]
    for _, r in ev.iterrows():
        out.append({"date": r["date"], "what": names.get(r["event"], r["event"])})
    for m in pd.period_range(last_day, end, freq="M"):
        first = m.to_timestamp()
        fridays = pd.date_range(first, first + pd.offsets.MonthEnd(0), freq="W-FRI")
        if len(fridays) >= 3 and last_day < fridays[2] <= end:
            out.append({"date": fridays[2], "what": "Monthly options expiration (3rd Friday)"})
        bme = first + pd.offsets.BMonthEnd(0)
        if last_day < bme <= end:
            out.append({"date": bme, "what": "Month-end (last weekday; holidays not checked)"})
    return sorted(out, key=lambda x: x["date"])
