"""Headlines for the Daily thesis: what the app first saw since the last close. Read-only.

Uses the first-seen archive (news_history.py). A headline is listed by when this app first received it, never
earlier, with its published time beside it so a late arrival is visible. Headlines are context: nothing here is
scored or turned into a signal.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from .data import NY

ARCHIVE = Path("data/news_history/headlines-v1.jsonl")
LIMIT = 12
SYMBOLS = ("SPY", "QQQ", "IWM", "*")  # the three index ETFs and market-wide sources (Fed releases)
STALE = pd.Timedelta(hours=24)  # a headline published more than a day before the last close is left out


def build(root: Path, now: pd.Timestamp, latest_close: str | None) -> dict:
    path = Path(root) / ARCHIVE
    if not path.exists() or not latest_close:
        return {"status": "unavailable", "rows": [], "reason": "No headlines archived yet."}
    since = pd.Timestamp(latest_close).tz_localize(NY) + pd.Timedelta(hours=16)
    seen, rows, newest = set(), [], None
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
            first = pd.Timestamp(row["first_seen_at"]).tz_convert(NY)
        except (ValueError, KeyError, TypeError):
            continue
        if first > now:
            continue
        newest = first if newest is None or first > newest else newest
        title = str(row.get("title") or "").strip()
        if first < since or not title or title.lower() in seen or row.get("symbol", "*") not in SYMBOLS:
            continue
        try:
            published = pd.Timestamp(row["published_at"]).tz_convert(NY) if row.get("published_at") else None
        except (ValueError, TypeError):
            published = None
        if published is not None and published < since - STALE:
            continue  # first seen now but published long ago (an old cache): not news since the close
        seen.add(title.lower())
        lag = (first - published).total_seconds() / 3600 if published is not None else None
        rows.append({"title": title, "publisher": row.get("publisher") or "", "symbol": row.get("symbol"),
                     "url": row.get("url"), "first_seen_et": f"{first:%Y-%m-%d %H:%M}",
                     "published_et": f"{published:%Y-%m-%d %H:%M}" if published is not None else None,
                     "late_hours": lag if lag is not None and lag >= 1 else None, "_key": first})
    rows.sort(key=lambda r: r.pop("_key"), reverse=True)
    return {"status": "ok", "since": f"{since:%Y-%m-%d %H:%M}", "count": len(rows), "rows": rows[:LIMIT],
            "last_collected_et": f"{newest:%Y-%m-%d %H:%M}" if newest is not None else None,
            "note": "Headlines the app first saw since the last close, newest first (Yahoo for SPY, QQQ and IWM, and "
                    "Federal Reserve releases). Collected at 9:00 AM, 3:50 PM, 4:05 PM and 8:10 PM ET, so a headline "
                    "can appear hours after it was published; the gap is shown."}
