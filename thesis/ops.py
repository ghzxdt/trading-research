"""System status for the Daily thesis: when each unattended job last did its work, and which days were missed.

Read-only. It reports what the saved files show; it never repairs anything. Replay builds show nothing, because
the files describe now, not the replayed moment.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pandas as pd

from .data import NY, last_known_session

MISSED_WINDOW = 15  # sessions looked back for missing paper decisions


def _row(label: str, state: str, last: str | None, detail: str) -> dict:
    return {"label": label, "state": state, "last": last, "detail": detail}


def _decisions(root: Path) -> dict[str, set]:
    """Signal date -> rule ids with a recorded decision in the frozen paper log (read without verifying)."""
    out: dict[str, set] = {}
    path = root / "data" / "monitor" / "paper_events.jsonl"
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        parts = str(event.get("key") or "").split(":")
        if event.get("type") == "decision" and len(parts) >= 3:
            out.setdefault(parts[1], set()).add(parts[2])
    return out


def _jsonl_dates(path: Path, key: str) -> list[str]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            out.append(str(json.loads(line).get(key) or ""))
        except ValueError:
            continue
    return [d for d in out if d]


def build(root: Path, now: pd.Timestamp, latest_close: str | None, check: dict | None = None) -> dict:
    if os.environ.get("APP_REPLAY") == "1":
        return {"status": "not_shown", "reason": "Not shown in a replay: these files describe today.", "rows": []}
    from validation import equity_sessions
    root = Path(root)
    today = now.tz_convert(NY)
    day = lambda ts: f"{pd.Timestamp(ts):%Y-%m-%d}"  # noqa: E731
    known = last_known_session(now)
    sessions = [day(s) for s in equity_sessions(known - pd.Timedelta(days=40), known)]
    latest = latest_close or (sessions[-1] if sessions else None)
    rows = []

    decisions = _decisions(root)
    last_decision = max(decisions) if decisions else None
    recent = [s for s in sessions[-MISSED_WINDOW:] if decisions and s >= min(decisions)]
    missed = [s for s in recent if s not in decisions and (not latest or s <= latest)]
    rows.append(_row("Paper decisions", "missing" if not decisions else "ok" if latest and last_decision >= latest and not missed else "late",
                     last_decision, ("No decisions recorded yet." if not decisions else
                                     f"Missed in the last {len(recent)} sessions: {', '.join(missed)}." if missed else
                                     f"Every session since {recent[0] if recent else last_decision} is recorded.")))

    stances = _jsonl_dates(root / "data" / "thesis" / "stance_log.jsonl", "latest_close")
    last_stance = max(stances) if stances else None
    rows.append(_row("Page stance log", "missing" if not stances else "ok" if latest and last_stance >= latest else "late",
                     last_stance, "Logged before the next open by an online refresh." if stances else "Nothing logged yet."))

    rows.append(_row("Page built from", "ok" if latest and sessions and latest >= sessions[-1] else "late", latest,
                     f"Built {today:%Y-%m-%d %H:%M} ET. The latest completed session is {sessions[-1] if sessions else 'unknown'}."))

    if check is not None:
        rows.append(_row("Backtested evidence", "ok" if check.get("usable") and not check.get("warning") else
                         "late" if check.get("usable") else "missing", check.get("checked_through"),
                         check.get("reason") or check.get("warning") or
                         (f"{check['age_days']} days before the latest close." if check.get("age_days") is not None else "Usable.")))

    snapshot = None
    futures = root / "data" / "futures" / "futures_quotes.csv"
    if futures.exists():
        try:
            stamps = pd.to_datetime(pd.read_csv(futures, usecols=["snapshot_utc"])["snapshot_utc"], utc=True, errors="coerce").dropna()
            snapshot = stamps.max().tz_convert(NY) if len(stamps) else None
        except (ValueError, OSError):
            snapshot = None
    age = (today - snapshot).total_seconds() / 3600 if snapshot is not None else None
    rows.append(_row("Market snapshots", "missing" if snapshot is None else "ok" if age < 30 else "late",
                     f"{snapshot:%Y-%m-%d %H:%M} ET" if snapshot is not None else None,
                     "Futures, Kalshi and the inflation nowcast, 9:00 AM and 4:05 PM ET." if snapshot is not None
                     else "No snapshot has been recorded on this computer yet."))

    collected = None
    try:
        status = json.loads((root / "data" / "terminal" / "collection_status.json").read_text(encoding="utf-8"))
        stamp = status.get("finished_at") or status.get("started_at")
        collected = pd.Timestamp(stamp).tz_convert(NY) if stamp else None
        results = status.get("results") or []
        got = sum(1 for r in results if r.get("bar_status") == "collected")
        detail = f"Minute bars for {got} of {len(results)} tickers in the last run."
    except (OSError, ValueError, TypeError):
        detail = "No collection recorded."
    age = (today - collected).total_seconds() / 3600 if collected is not None else None
    rows.append(_row("Intraday collection", "missing" if collected is None else "ok" if age < 30 else "late",
                     f"{collected:%Y-%m-%d %H:%M} ET" if collected is not None else None, detail))

    samples = sorted(p.stem for p in (root / "data" / "liquidity" / "samples").glob("*.jsonl")) if (root / "data" / "liquidity" / "samples").is_dir() else []
    rows.append(_row("Liquidity samples", "missing" if not samples else "ok" if latest and samples[-1] >= latest else "late",
                     samples[-1] if samples else None,
                     f"{len(samples)} sampled day(s); the intraday gate needs 20 complete ones." if samples
                     else "No daytime sample has run yet (10:30 AM, 12:30, 2:30 and 3:50 PM ET)."))

    backups = sorted(p.stem[-10:] for p in (root / "backups" / "data").glob("trading-research-data-*.zip")) if (root / "backups" / "data").is_dir() else []
    rows.append(_row("Data backup", "missing" if not backups else "ok" if latest and backups[-1] >= latest else "late",
                     backups[-1] if backups else None, "Saved in backups/data on this computer (copied by hand from C:\\Claude)."))

    worst = "missing" if any(r["state"] == "missing" for r in rows) else "late" if any(r["state"] == "late" for r in rows) else "ok"
    return {"status": worst, "rows": rows, "missed_decisions": missed,
            "note": "Late means the last result is older than the latest completed session. Missed paper decisions "
                    "cannot be added afterwards: they are only recorded before the next open."}
