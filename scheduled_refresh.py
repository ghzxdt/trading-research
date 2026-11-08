"""Weekday evening refresh, run by the Windows scheduled task "Trading Research Evening Refresh".

Steps:
1. If the paper log already has the latest completed session's decisions, go to step 5.
2. Wait until Cboe has posted that session's VIX close, checking every 15 minutes. A refresh
   before then logs the session as data_blocked, and the append-only log can't be corrected.
3. Run the app's own Run / Refresh data path (app_control.Controller.refresh), so the build
   lock and the dashboard's busy checks apply exactly as they do for the button.
4. Check that the decisions were logged; if not, try again every 15 minutes. At the deadline
   (9:00 AM ET the next morning, before the 9:30 entry) refresh once regardless, so a missing
   VIX close is logged as data_blocked instead of leaving a silent gap.
5. Commit the data files the refresh changed and push main to GitHub (git_backup.py).

It never trades and never commits code. Log: work/scheduled_refresh.log.
Exit codes: 0 decisions logged before entry; 1 logged but late or data-blocked;
2 not logged by the deadline; 3 unexpected error.
"""
from __future__ import annotations

import argparse
import json
import time
import traceback
from datetime import date, datetime, time as wall_clock, timedelta
from pathlib import Path

import pandas as pd
import requests

import git_backup
from app_control import ControlError, Controller
from validation import NY, equity_sessions, expected_session

ROOT = Path(__file__).resolve().parent
LOG_PATH = ROOT / "work" / "scheduled_refresh.log"
CHECK_EVERY = pd.Timedelta(minutes=15)
BUILD_TIMEOUT = pd.Timedelta(minutes=60)
SCORED_STATES = {"recorded_before_entry", "overlap_skipped"}


def log(message: str) -> None:
    line = f"[{pd.Timestamp.now(tz=NY):%Y-%m-%d %H:%M:%S} ET] {message}"
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as stream:
        stream.write(line + "\n")
    print(line, flush=True)  # no-op under pythonw, where there is no console


def at_et(day, hour: int, minute: int = 0) -> pd.Timestamp:
    """A wall-clock time in New York on the given calendar day."""
    return pd.Timestamp(datetime.combine(pd.Timestamp(day).date(), wall_clock(hour, minute))).tz_localize(NY)


def deadline_for(start: pd.Timestamp, session) -> pd.Timestamp:
    """9:00 AM ET on the session after `session` (half an hour before its open), but no later
    than the first 9:00 AM ET after `start`, so a Friday run doesn't wait all weekend."""
    session = pd.Timestamp(session).normalize()
    following = equity_sessions(session + pd.Timedelta(days=1), session + pd.Timedelta(days=14))[0]
    day = start.tz_convert(NY).date()
    morning = at_et(day, 9)
    if start >= morning:
        morning = at_et(day + timedelta(days=1), 9)
    return min(at_et(following, 9), morning)


def newest_csv_date(text: str) -> date | None:
    """Date of the last data row in a Cboe daily history CSV (MM/DD/YYYY first column)."""
    for line in reversed(text.strip().splitlines()):
        try:
            return datetime.strptime(line.split(",", 1)[0].strip(), "%m/%d/%Y").date()
        except ValueError:
            continue
    return None


def last_vix_date() -> date | None:
    """Newest date in Cboe's VIX history file: the same file the refresh downloads."""
    from stage1.sources import CBOE_URL, HEADERS
    response = requests.get(CBOE_URL.format(name="VIX"), headers=HEADERS, timeout=60)
    response.raise_for_status()
    return newest_csv_date(response.text)


def decision_states(root: Path, session) -> dict[str, str] | None:
    """State of each rule's decision for `session`, or None until every frozen rule has one."""
    from monitor.paper import read_log  # verifies the hash chain on every read
    lock = json.loads((root / "data/monitor/experiment_lock.json").read_text(encoding="utf-8"))
    day = pd.Timestamp(session).date().isoformat()
    keys = {f"{lock['version']}:{day}:{rule['id']}" for rule in lock["strategies"]}
    found = {e["key"]: e["state"] for e in read_log(root / "data/monitor/paper_events.jsonl")
             if e.get("type") == "decision" and e.get("key") in keys}
    return found if set(found) == keys else None


def app_refresh(controller: Controller, say=log, sleep=time.sleep, monotonic=time.monotonic) -> str:
    """Press Run / Refresh data through the dashboard server and wait for the build to finish.

    If a refresh is already running (for example one started from the control panel), wait for
    that one instead. If this call started the dashboard server, stop it again afterwards."""
    before = controller.status()
    if before.get("running") and not before.get("identity_ok"):
        return "Refresh not started: " + str(before.get("message"))
    started_server = not before.get("running")
    try:
        note = ""
        if before.get("busy"):
            note = "A refresh was already running; waited for it. "
        else:
            try:
                controller.refresh(offline=False)
            except ControlError as exc:
                if "already active" not in str(exc):
                    return f"Refresh not started: {exc}"
                note = "A refresh was already running; waited for it. "
        give_up = monotonic() + BUILD_TIMEOUT.total_seconds()
        status = controller.status()
        while status.get("busy") or (status.get("build") or {}).get("running"):
            if monotonic() > give_up:
                return note + "Refresh still running after 60 minutes; left it running."
            sleep(10)
            status = controller.status()
        build = status.get("build") or {}
        return note + ("Refresh succeeded." if build.get("ok") else f"Refresh failed: {build.get('message')}")
    finally:
        if started_server and controller.status().get("running"):
            try:
                controller.stop()  # refuses while a build is still writing
            except ControlError as exc:
                say(f"Dashboard left running: {exc}")


def report(found: dict[str, str], say) -> int:
    unscored = sorted({state for state in found.values() if state not in SCORED_STATES})
    if unscored:
        say(f"Decisions logged as {', '.join(unscored)}; they won't count in the forward score.")
        return 1
    say("Decisions logged before entry.")
    return 0


def run(root: Path = ROOT, *, say=log, now=lambda: pd.Timestamp.now(tz=NY), sleep=time.sleep,
        vix_date=last_vix_date, states=decision_states, refresh=None, backup=None) -> int:
    start = now()
    session = expected_session(start)
    deadline = deadline_for(start, session)
    say(f"Started. Latest completed session: {session:%a %b %d}. Deadline: {deadline:%a %b %d %I:%M %p} ET.")
    code = 2
    while True:
        found = states(root, session)
        if found is not None:
            code = report(found, say)
            break
        moment = now()
        final = moment >= deadline
        try:
            newest = vix_date()
        except Exception as exc:  # network trouble counts as "not posted yet"
            newest = None
            say(f"Could not read Cboe's VIX file: {exc}")
        ready = newest is not None and newest >= session.date()
        if ready or final:
            if not ready:
                say("Deadline reached without the VIX close; refreshing anyway so the gap is logged as data blocked.")
            say("Running Run / Refresh data.")
            say(refresh() if refresh else "No refresh function given.")
            found = states(root, session)
            if found is not None:
                code = report(found, say)
                break
            say(f"No decisions for {session:%b %d} in the paper log yet.")
        else:
            say(f"Cboe's VIX file ends {newest}; waiting for {session:%b %d}.")
        if final:
            say(f"Deadline passed without decisions for {session:%b %d}.")
            break
        sleep(max(min(CHECK_EVERY, deadline - moment).total_seconds(), 1.0))
    if backup:
        backup()
    return code


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--no-git", action="store_true", help="skip the data commit and GitHub push")
    args = parser.parse_args(argv)
    try:
        today = pd.Timestamp.now(tz=NY).date().isoformat()
        return run(ROOT, refresh=lambda: app_refresh(Controller(ROOT)),
                   backup=None if args.no_git else (lambda: git_backup.sync(ROOT, log, f"Evening refresh data, {today}")))
    except Exception:
        log("Unexpected error:\n" + traceback.format_exc())
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
