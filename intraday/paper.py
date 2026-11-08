"""Separate frozen intraday paper journal. Never writes legacy experiments or orders."""
from __future__ import annotations
import math
import re
import pandas as pd
from .store import folder, readonly, read_events, writer_lock, append_events, digest
from .calendar import utc, session, date_of
from .features import STUDY_ID, PARAMETERS
from .backtest import configuration


def read_log(root):
    return read_events(folder(root) / "paper.jsonl")


def _experiment(events, version, config, qualification_policy=None):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.\-]{0,79}", version):
        raise ValueError("Invalid experiment version")
    spec = {"version": version, "study_id": STUDY_ID, "parameters": dict(PARAMETERS), "execution_config": configuration(config)}
    if qualification_policy is not None:
        spec['qualification_policy'] = qualification_policy
    if spec["execution_config"]["assume_bar_close_availability"]:
        raise ValueError("Assumed archive timing cannot be used for forward paper experiments")
    frozen = [e for e in events if e["type"] == "experiment" and e["spec"]["version"] == version]
    if frozen and frozen[0]["spec"] != spec:
        raise ValueError("Frozen intraday experiment changed; use a new version")
    if not frozen and sum(e["type"] == "experiment" for e in events) >= 20:
        raise ValueError("Study registry capped at 20 explicitly versioned experiments; no automatic search")
    return spec, not frozen


def record_decision(root, snapshot, *, version=STUDY_ID, config=None, entry_at=None, now=None, replay=False, qualification_policy=None):
    if replay or readonly():
        return {"recorded": False, "state": "replay_read_only"}
    now = utc(now) if now is not None else pd.Timestamp.now(tz="UTC")
    as_of = utc(snapshot["as_of"])
    if as_of > now:
        raise ValueError("Cannot record a decision using a future snapshot")
    quality, signal = snapshot.get("quality", {}), snapshot.get("signal", {})
    if not snapshot.get("snapshot_id") or not snapshot.get("symbol") or not snapshot.get("session", {}).get("date"):
        raise ValueError("A reproducible symbol/session snapshot is required")
    c = configuration(config)
    planned = utc(entry_at) if entry_at else (now + pd.Timedelta(seconds=c["latency_seconds"])).ceil("min")
    market = session(date_of(now))
    flatten = utc(market["close"]) - pd.Timedelta(minutes=c["flatten_minutes_before_close"]) if market.get("is_session") else None
    if signal.get("state") != "candidate":
        state = "abstain"
    elif not quality.get("forward_eligible") or quality.get("availability_bases") != ["observed_live"]:
        state = "data_blocked"
    elif ((now - as_of).total_seconds() > 120 or snapshot["session"]["date"] != date_of(now) or
          not market.get("calendar_verified") or flatten is None or
          not utc(market["open"]) <= now < planned < flatten):
        state = "late_unscored"
    else:
        state = "recorded_before_entry"
    decision_id = digest({"version": version, "symbol": snapshot["symbol"], "snapshot_id": snapshot["snapshot_id"]})
    directory = folder(root)
    with writer_lock(directory):
        path = directory / "paper.jsonl"
        events = read_events(path)
        spec, create = _experiment(events, version, c, qualification_policy)
        old = next((e for e in events if e.get("decision_id") == decision_id and e["type"] == "decision"), None)
        if old:
            return {"recorded": False, "state": "duplicate", "event": old}
        if state == "recorded_before_entry" and any(e["type"] == "decision" and e.get("version") == version and
                e.get("symbol") == snapshot["symbol"] and e.get("session") == snapshot["session"]["date"] and
                e.get("state") == "recorded_before_entry" for e in events):
            state = "session_trade_already_recorded"
        payloads = [{"schema_version": 1, "type": "experiment", "recorded_at": now.isoformat(), "spec": spec,
                     "spec_hash": digest(spec)}] if create else []
        payloads.append({"schema_version": 1, "type": "decision", "decision_id": decision_id,
                         "version": version, "symbol": snapshot["symbol"], "session": snapshot["session"]["date"],
                         "recorded_at": now.isoformat(), "as_of": as_of.isoformat(), "snapshot_id": snapshot["snapshot_id"],
                         "entry_at": planned.isoformat(), "state": state, "signal": signal,
                         "quality": quality, "paper_only": True, "orders_sent": False})
        event = append_events(path, events, payloads)[-1]
    return {"recorded": True, "state": state, "event": event}


def record_outcome(root, decision_id, outcome, *, now=None, replay=False):
    if replay or readonly():
        return {"recorded": False, "state": "replay_read_only"}
    now = utc(now) if now is not None else pd.Timestamp.now(tz="UTC")
    net = float(outcome["net_return"])
    exit_at = utc(outcome["exit_at"])
    if not math.isfinite(net) or exit_at > now or not outcome.get("fill_model"):
        raise ValueError("Outcome requires finite net return, observed past exit and an explicit paper fill model")
    directory = folder(root)
    with writer_lock(directory):
        path = directory / "paper.jsonl"
        events = read_events(path)
        decision = next((e for e in events if e["type"] == "decision" and e["decision_id"] == decision_id), None)
        if not decision or decision["state"] != "recorded_before_entry":
            raise ValueError("Only an eligible decision recorded before entry may receive a forward paper outcome")
        if exit_at <= utc(decision["entry_at"]):
            raise ValueError("Outcome exit must follow the planned entry")
        if any(e["type"] == "outcome" and e["decision_id"] == decision_id for e in events):
            return {"recorded": False, "state": "duplicate"}
        event = append_events(path, events, [{"schema_version": 1, "type": "outcome", "decision_id": decision_id,
                    "recorded_at": now.isoformat(), "outcome": {**outcome, "net_return": net, "exit_at": exit_at.isoformat()},
                    "paper_only": True}])[-1]
    return {"recorded": True, "event": event}
