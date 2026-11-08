"""Earnings dates for the largest Nasdaq-100 / S&P 500 companies, from two free sources.

- Yahoo Finance (yfinance): next and past report dates with a time stamp.
- Nasdaq.com (its public analyst endpoint, Zacks data): the expected date and "before open" / "after close".
The two are shown side by side; a disagreement is flagged instead of picking one. Past Yahoo dates give the
historical comparison: QQQ's absolute move on each company's earnings-reaction session versus a normal session.

An online refresh downloads to data/raw/earnings/earnings.json; offline builds only read it.
"""
from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

from .data import NY

COMPANIES = (("NVDA", "Nvidia"), ("AAPL", "Apple"), ("MSFT", "Microsoft"), ("AMZN", "Amazon"),
             ("GOOGL", "Alphabet"), ("META", "Meta"), ("AVGO", "Broadcom"), ("TSLA", "Tesla"),
             ("NFLX", "Netflix"), ("COST", "Costco"))
FILE = Path("data/raw/earnings/earnings.json")
NASDAQ_URL = "https://api.nasdaq.com/api/analyst/{symbol}/earnings-date"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) personal-research-script",
           "Accept": "application/json"}


def yahoo_dates(symbol: str) -> list[dict]:
    import yfinance as yf
    frame = yf.Ticker(symbol).get_earnings_dates(limit=16)
    if frame is None or frame.empty:
        return []
    rows = []
    for stamp, row in frame.iterrows():
        local = pd.Timestamp(stamp).tz_convert(NY)
        rows.append({"date": f"{local:%Y-%m-%d}", "time_et": f"{local:%H:%M}",
                     "eps_estimate": None if pd.isna(row.get("EPS Estimate")) else float(row["EPS Estimate"]),
                     "reported_eps": None if pd.isna(row.get("Reported EPS")) else float(row["Reported EPS"])})
    return sorted(rows, key=lambda r: r["date"])


def nasdaq_date(symbol: str, get=requests.get) -> dict:
    response = get(NASDAQ_URL.format(symbol=symbol), headers=HEADERS, timeout=30)
    response.raise_for_status()
    text = ((response.json() or {}).get("data") or {}).get("reportText") or ""
    found = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", text)
    timing = ("after close" if "after market close" in text else "before open" if "before market open" in text
              else None)
    return {"date": f"{found.group(3)}-{int(found.group(1)):02d}-{int(found.group(2)):02d}" if found else None,
            "timing": timing, "expected": "expected*" in text, "text": text[:400]}


def refresh(root: Path, yahoo=yahoo_dates, nasdaq=nasdaq_date, pause: float = 0.3) -> dict:
    path = Path(root) / FILE
    previous = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    out = {"fetched_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "companies": {}}
    for symbol, name in COMPANIES:
        entry, old = {"name": name}, (previous.get("companies") or {}).get(symbol, {})
        for key, fetch in (("yahoo", yahoo), ("nasdaq", nasdaq)):
            try:
                entry[key] = fetch(symbol)
                entry[f"{key}_ok"] = True
            except Exception as exc:  # keep the last good copy, marked as such
                entry[key] = old.get(key)
                entry[f"{key}_ok"] = False
                entry[f"{key}_error"] = str(exc)[:200]
            time.sleep(pause)
        out["companies"][symbol] = entry
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(out, indent=1), encoding="utf-8")
    temp.replace(path)
    return {s: {"yahoo": e.get("yahoo_ok"), "nasdaq": e.get("nasdaq_ok")} for s, e in out["companies"].items()}


def reaction_session(index: pd.DatetimeIndex, date: str, time_et: str | None, timing: str | None):
    day = pd.Timestamp(date)
    after = timing == "after close" or (time_et is not None and time_et >= "16:00")
    later = index[index > day] if after else index[index >= day]
    return later[0] if len(later) else None


def build(root: Path, now, etfs: dict, days_ahead: int = 45) -> dict:
    path = Path(root) / FILE
    if not path.exists():
        return {"status": "unavailable", "rows": [],
                "reason": "Earnings dates not downloaded yet; the next online refresh fetches them."}
    saved = json.loads(path.read_text(encoding="utf-8"))
    today = now.tz_convert(NY).normalize().tz_localize(None)
    qqq = etfs.get("QQQ")
    moves = qqq["close"].pct_change().abs().dropna() if qqq is not None else pd.Series(dtype=float)
    rows = []
    for symbol, name in COMPANIES:
        entry = (saved.get("companies") or {}).get(symbol) or {}
        yahoo = entry.get("yahoo") or []
        nasdaq = entry.get("nasdaq") or {}
        future = [r for r in yahoo if pd.Timestamp(r["date"]) >= today]
        nxt = future[0] if future else None
        nasdaq_next = nasdaq.get("date") if nasdaq.get("date") and pd.Timestamp(nasdaq["date"]) >= today else None
        if not nasdaq_next:
            nasdaq = {}
        dates = {d for d in ((nxt or {}).get("date"), nasdaq_next) if d}
        agree = ("agree" if len(dates) == 1 and nxt and nasdaq_next else "differ" if len(dates) > 1
                 else "one source" if dates else "none")
        reactions = []
        for r in yahoo:
            if pd.Timestamp(r["date"]) >= today or moves.empty:
                continue
            session = reaction_session(moves.index, r["date"], r.get("time_et"), None)
            if session is not None and session in moves.index:
                reactions.append(float(moves.loc[session]))
        first = min(dates) if dates else None
        rows.append({"symbol": symbol, "name": name, "next_yahoo": nxt, "next_nasdaq": nasdaq or None,
                     "agreement": agree, "next_date": first,
                     "within_window": bool(first and pd.Timestamp(first) <= today + pd.Timedelta(days=days_ahead)),
                     "past_reactions": len(reactions),
                     "median_qqq_move": float(pd.Series(reactions).median()) if reactions else None,
                     "yahoo_ok": entry.get("yahoo_ok"), "nasdaq_ok": entry.get("nasdaq_ok")})
    rows.sort(key=lambda r: r["next_date"] or "9999")
    normal = float(moves[moves.index >= moves.index[-1] - pd.DateOffset(years=4)].median()) if len(moves) else None
    return {"status": "ok", "fetched_utc": saved.get("fetched_utc"), "rows": rows, "normal_qqq_move": normal,
            "note": "QQQ's absolute close-to-close move on each company's earnings-reaction session (the next "
                    "session for an after-close report) over the dates Yahoo lists (about 4 years), versus QQQ's "
                    "median move on all sessions in the last 4 years."}
