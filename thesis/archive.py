"""Daily archive of the page's key values: one append-only, hash-chained record per close.

thesis_state.json is replaced at every build, so what the page showed on a given evening survives only if it is
kept going forward (backtester review, 2026-11-18). Rules, fixed 2026-11-18:
- Written only by recording online builds (the evening task's refresh, or a manual refresh after Cboe has posted
  the VIX close), at the same moment as the stance log. Offline, replay and data-only builds never write.
- At most one record per latest close; the first one stands. Only while that close's next open is still ahead,
  so a record is always the evening (or pre-open) view of that close, never a later one.
- Values are copied from the built page, not recomputed: stance and evidence status, regime condition, VIX and
  VIX/VIX3M, trend, credit and rates, breadth, events and earnings in the next 5 sessions, the news count, the
  futures move when a snapshot exists (every snapshot is also kept in data/futures), large moves in the biggest
  holdings, and each rule's state and distance to its trigger.
- Never edited by hand (append-only, hash-chained; a correction is a new record).
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from . import calls, eligibility
from .data import NY

LOG = Path("data/thesis/daily_archive.jsonl")
SCHEMA = 1
SESSIONS_AHEAD = 5


def _pick(row: dict | None, *keys: str) -> dict:
    return {k: (row or {}).get(k) for k in keys}


def record(state: dict) -> dict:
    """The archive's values for the page's latest close (no hash, id or timestamps)."""
    latest = state["latest_close"]
    reg = state.get("regime") or {}
    window = list(pd.bdate_range(pd.Timestamp(latest) + pd.Timedelta(days=1), periods=SESSIONS_AHEAD))
    end = f"{window[-1]:%Y-%m-%d}"  # weekdays: holidays aren't excluded, as on the page
    inside = lambda day: bool(day) and latest < day <= end  # noqa: E731
    events = [_pick(e, "date", "label") for e in (reg.get("events") or {}).get("upcoming") or [] if inside(e.get("date"))]
    mega = sorted({(r["next_date"], r.get("name")) for r in (state.get("earnings") or {}).get("rows") or []
                   if inside(r.get("next_date"))})
    calendar = [{"date": d["date"], "symbols": [r.get("symbol") for r in d.get("rows") or []][:25]}
                for d in (state.get("earnings_calendar") or {}).get("days") or [] if inside(d.get("date")) and d.get("rows")]
    view, check = state.get("view") or {}, state.get("evidence_check") or {}
    futures = view.get("futures") or {}
    rules = []
    for s in state.get("signals") or []:
        trigger, close = s.get("trigger_close"), s.get("close")
        rules.append({**_pick(s, "symbol", "signal", "value", "close", "trigger_close"),
                      "fired": bool(s.get("fired")),  # json_safe would turn a numpy bool into the string "True"
                      "distance": trigger / close - 1 if trigger and close else None,
                      "next_open_verdicts": sorted({e.get("verdict") for e in s.get("evidence") or []
                                                    if e.get("mode") == eligibility.ENTRY_MODE})})
    from today.build import json_safe  # strict JSON: numpy numbers become plain ones, NaN becomes null
    return json_safe({
        "page_as_of": state.get("as_of"),
        "stance": _pick(state.get("stance"), "direction", "status", "headline"),
        "evidence": {**_pick(check, "status", "usable", "checked_through", "age_days"),
                     "verdict_version": (state.get("evidence_source") or {}).get("verdict_version"),
                     "sha256": (state.get("evidence_source") or {}).get("sha256")},
        "condition": (reg.get("history") or {}).get("condition"),
        "volatility": _pick(reg.get("volatility"), "date", "vix", "vix3m", "term_ratio", "bucket", "change_5d",
                            "percentile_10y", "realized_20d", "implied_daily_move"),
        "trend": {k: _pick(v, "date", "close", "vs_sma50", "vs_sma200", "return_20d") for k, v in (reg.get("trend") or {}).items()},
        "credit": [_pick(c, "series", "date", "value", "change_1m", "percentile") for c in reg.get("credit") or []],
        "rates": _pick(reg.get("rates"), "date", "two_year", "ten_year", "curve"),
        "breadth": _pick(reg.get("breadth"), "date", "relative_20d", "relative_60d"),
        "events_next_5": events,
        "mega_cap_earnings_next_5": [{"date": d, "name": n} for d, n in mega],
        "earnings_calendar_next_5": calendar,
        "news": _pick(state.get("news"), "count", "since", "last_collected_et"),
        "futures": {"mode": view.get("mode"), **_pick(futures, "status", "snapshot_et"),
                    "rows": [_pick(r, "symbol", "name", "change_since_4pm") for r in futures.get("rows") or []]},
        "movers_flagged": [_pick(r, "name", "move") for r in (state.get("movers") or {}).get("flagged") or []],
        "rules": rules,
    })


def append_daily(root: Path, state: dict, now: pd.Timestamp, entry_time=None) -> dict:
    """Append the record for the page's latest close if it's new and that close's next open is still ahead."""
    if entry_time is None:
        from refresh_guard import entry_time
    latest = state.get("latest_close")
    if not latest:
        return {"logged": 0, "skipped": "no latest close"}
    deadline = entry_time(pd.Timestamp(latest))
    if now >= deadline:
        return {"logged": 0, "skipped": f"too late: the {latest} close's next open ({deadline:%Y-%m-%d %H:%M} ET) has passed"}
    rows = calls.read(root, LOG)
    if any(r.get("latest_close") == latest for r in rows):
        return {"logged": 0, "skipped": f"the {latest} close is already archived"}
    body = {"schema": SCHEMA, "id": len(rows) + 1, "latest_close": latest,
            "recorded_utc": now.tz_convert("UTC").isoformat(timespec="seconds"),
            "recorded_et": now.tz_convert(NY).isoformat(timespec="seconds"),
            **record(state), "previous_hash": rows[-1]["hash"] if rows else ""}
    row = {**body, "hash": calls._digest(body)}
    path = Path(root) / LOG
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n")
    return {"logged": 1, "skipped": None}


def summary(root: Path) -> dict:
    check = calls.verify(root, LOG)
    if not check["ok"]:
        return {"status": "broken", "reason": check["reason"], "count": 0}
    rows = calls.read(root, LOG)
    return {"status": "ok" if rows else "empty", "count": len(rows),
            "first": rows[0]["latest_close"] if rows else None, "last": rows[-1]["latest_close"] if rows else None}
