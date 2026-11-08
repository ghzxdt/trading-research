"""Guard against an online refresh that would log the day's paper decisions as data_blocked.

The paper log records each frozen rule's decision for the latest completed session on the first
online refresh after 4:30 PM ET, and it is append-only. Cboe posts the VIX close later than that
(about 5:30 PM ET or after), and the app treats the session's data as incomplete until it has. A
refresh in that gap therefore records the session as data_blocked, for good.

blocking_reason() says whether an online refresh right now would do that. The local dashboard
server refuses such a refresh with that reason (the control panel and the dashboard both show it),
run_all.py does the same from the command line, and the evening task overrides it only at its
9:00 AM ET deadline, when logging the gap is the honest outcome. Offline rebuilds never record
decisions, so they are never blocked.
"""
from __future__ import annotations

import json
from datetime import date, datetime, time as wall_clock
from pathlib import Path

import pandas as pd
import requests

# Imported here, not per call, so the dashboard server pays the import cost at startup and the
# check itself stays well under a second (an older control panel waits only 1.2 s for an answer).
from monitor.paper import read_log  # verifies the hash chain on every read
from stage1.sources import CBOE_URL, HEADERS
from validation import NY, equity_sessions, expected_session


def newest_csv_date(text: str) -> date | None:
    """Date of the last data row in a Cboe daily history CSV (MM/DD/YYYY first column)."""
    for line in reversed(text.strip().splitlines()):
        try:
            return datetime.strptime(line.split(",", 1)[0].strip(), "%m/%d/%Y").date()
        except ValueError:
            continue
    return None


def last_vix_date(timeout: int = 10) -> date | None:
    """Newest date in Cboe's VIX history file: the same file the refresh downloads (~0.3 s)."""
    response = requests.get(CBOE_URL.format(name="VIX"), headers=HEADERS, timeout=timeout)
    response.raise_for_status()
    return newest_csv_date(response.text)


def decision_states(root: Path, session) -> dict[str, str] | None:
    """State of each frozen rule's decision for `session`, or None until every rule has one."""
    lock = json.loads((Path(root) / "data/monitor/experiment_lock.json").read_text(encoding="utf-8"))
    day = pd.Timestamp(session).date().isoformat()
    keys = {f"{lock['version']}:{day}:{rule['id']}" for rule in lock["strategies"]}
    found = {e["key"]: e["state"] for e in read_log(Path(root) / "data/monitor/paper_events.jsonl")
             if e.get("type") == "decision" and e.get("key") in keys}
    return found if set(found) == keys else None


def entry_time(session) -> pd.Timestamp:
    """9:30 AM ET on the session after `session`, when its decisions' hypothetical entries start."""
    session = pd.Timestamp(session).normalize()
    following = equity_sessions(session + pd.Timedelta(days=1), session + pd.Timedelta(days=14))[0]
    return pd.Timestamp(datetime.combine(following.date(), wall_clock(9, 30))).tz_localize(NY)


def blocking_reason(root: Path, now: pd.Timestamp | None = None, vix_date=last_vix_date,
                    states=decision_states) -> str | None:
    """Why an online refresh now would log the latest session as data_blocked, or None if it's safe."""
    now = now if now is not None else pd.Timestamp.now(tz=NY)
    session = expected_session(now)
    try:
        if states(root, session) is not None:
            return None  # already recorded; a refresh can't add or change those decisions
    except FileNotFoundError:
        pass  # no experiment or log yet: the refresh would create the first decisions
    except Exception:
        return None  # e.g. a broken hash chain: the build itself reports it
    if now >= entry_time(session):
        return None  # too late to count either way; a refresh records the day honestly as late
    day = f"{session:%a %b} {session.day}"
    try:
        newest = vix_date()
    except Exception as exc:
        return (f"Couldn't check whether Cboe has posted the VIX close for {day} ({exc}). Refreshing without it "
                "would log that day's paper decisions as data-blocked for good. Try again in a few minutes; "
                "Rebuild saved data is safe at any time.")
    if newest is None or newest < session.date():
        ends = f"{newest:%b} {newest.day}" if newest else "an unknown date"
        return (f"Cboe hasn't posted the VIX close for {day} yet (its file ends {ends}). Refreshing now would log "
                "that day's paper decisions as data-blocked for good. The evening task refreshes automatically "
                "once it's posted; Rebuild saved data is safe at any time.")
    return None
