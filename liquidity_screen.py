"""Causal liquidity policy from declared-verified session aggregates; no fetches.

Thresholds are required research policy, not scientific execution guarantees.
Imports attest to source quality; validation cannot certify a vendor's claims.
Current-chain indications never enter this dedicated history automatically.
"""
from __future__ import annotations

import math
import re
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from intraday.calendar import session, utc
from intraday.store import append_events, read_events, readonly, writer_lock

VERSION = 1
WINDOW = 20
REQUIRED_FRACTION = .8
METRICS = ("share_volume", "share_median_spread_bps", "options_volume", "options_median_spread_bps")


def _number(value, label, *, optional=False):
    if value is None and optional:
        return None
    if isinstance(value, bool):
        raise ValueError(label + " cannot be boolean")
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(label + " must be finite and nonnegative") from exc
    if not math.isfinite(result) or result < 0:
        raise ValueError(label + " must be finite and nonnegative")
    return result


def _day(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError("session_date must be an ISO date")
    return date.fromisoformat(value)


def _symbol(value):
    if not isinstance(value, str):
        raise ValueError("Invalid liquidity symbol")
    value = str(value).strip().upper()
    if not re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,14}", value):
        raise ValueError("Invalid liquidity symbol")
    return value


def normalize(record):
    if not isinstance(record, dict):
        raise ValueError("A liquidity record must be an object")
    day = _day(record.get("session_date"))
    bounds = session(day.isoformat())
    if not bounds.get("is_session") or not bounds.get("calendar_verified"):
        raise ValueError("Liquidity session requires verified exchange-calendar coverage")
    complete = record.get("complete_session")
    if not isinstance(complete, bool):
        raise ValueError("complete_session must be explicitly boolean")
    source = str(record.get("source") or "").strip()
    if not source or len(source) > 200:
        raise ValueError("A source identifier is required")
    if record.get("spread_basis") != "midpoint":
        raise ValueError("spread_basis must be midpoint; spreads must be expressed in basis points")
    method = record.get("metric_method")
    if not isinstance(method, str) or not method.strip():
        raise ValueError("metric_method must declare quote-time and coverage methodology")
    observed, known = utc(record.get("source_timestamp")), utc(record.get("available_at"))
    if observed < utc(bounds["close"] if complete else bounds["open"]) or known < observed:
        raise ValueError("Session metrics cannot be published before their covered observations")
    values = {name: _number(record.get(name), name, optional=True) for name in METRICS}
    options_scope = record.get("options_scope")
    if any(values[name] is not None for name in ("options_volume", "options_median_spread_bps")):
        if not isinstance(options_scope, (str, dict)) or not options_scope or (
                isinstance(options_scope, str) and not options_scope.strip()):
            raise ValueError("Nonempty options_scope is required whenever options metrics are supplied")
    for name in ("share_volume", "options_volume"):
        if values[name] is not None and not values[name].is_integer():
            raise ValueError(name + " must count actual whole shares or contracts")
    result = {"schema_version": VERSION, "symbol": _symbol(record.get("symbol", "")),
            "session_date": day.isoformat(), "complete_session": complete, "source": source,
            "source_timestamp": observed.isoformat(), "available_at": known.isoformat(),
            "spread_basis": "midpoint", "metric_method": method.strip(), **values}
    if options_scope is not None:
        result["options_scope"] = json.loads(json.dumps(options_scope, allow_nan=False))
    for name in ("method", "contract_scope", "share_spread_basis", "options_spread_basis",
                 "options_volume_scope", "source_url", "verification_note", "provenance"):
        if name in record:
            result[name] = json.loads(json.dumps(record[name], allow_nan=False))
    return result


# Separate journals, never mixed. "verified" holds imported full-session aggregates (the strict default).
# "snapshot" holds the declared free policy built by liquidity_free.py: spreads are medians of a few intraday
# quote snapshots, not full-session quote medians, so results using it must say so.
JOURNALS = {"verified": ("v1", "sessions.jsonl"), "snapshot": ("snapshot-v1", "sessions.jsonl")}


def _path(root, journal="verified"):
    if journal not in JOURNALS:
        raise ValueError("Unknown liquidity journal " + repr(journal))
    return Path(root) / "data" / "liquidity" / JOURNALS[journal][0] / JOURNALS[journal][1]


def _load(root, journal="verified"):
    rows = {}
    for event in read_events(_path(root, journal)):
        if event.get("type") != "liquidity_session" or event.get("schema_version") != VERSION:
            raise ValueError("Unexpected liquidity-journal record")
        row = normalize(event["record"])
        key = row["symbol"], row["session_date"]
        if key in rows and rows[key] != row:
            raise ValueError("Conflicting immutable liquidity session")
        rows[key] = row
    return rows


def import_verified(root, records, journal="verified"):
    """Append attested session aggregates; exact duplicates deduplicate, conflicts reject."""
    if readonly():
        raise PermissionError("Replay/offline mode cannot import liquidity history")
    proposed = [normalize(row) for row in records]
    path = _path(root, journal)
    with writer_lock(path.parent):
        events, existing = read_events(path), _load(root, journal)
        additions, duplicates = [], 0
        for row in proposed:
            key = row["symbol"], row["session_date"]
            if key in existing:
                if existing[key] != row:
                    raise ValueError("Conflicting immutable liquidity session; preserve the journal")
                duplicates += 1
                continue
            existing[key] = row
            additions.append({"schema_version": VERSION, "type": "liquidity_session",
                              "recorded_at": datetime.now(timezone.utc).isoformat(), "record": row})
        append_events(path, events, additions)
    return {"schema_version": VERSION, "accepted": len(additions), "duplicates": duplicates, "journal": journal,
            "path": str(path), "source_verification": "Declared by importer; not independently certified"}


def _prior(day):
    days, cursor = [], _day(day)
    for _ in range(65):
        cursor -= timedelta(days=1)
        bounds = session(cursor.isoformat())
        if not bounds.get("calendar_verified"):
            raise ValueError("Twenty prior sessions exceed verified calendar coverage")
        if bounds.get("is_session"):
            days.append(cursor.isoformat())
            if len(days) == WINDOW:
                return list(reversed(days))
    raise ValueError("Twenty preceding exchange sessions unavailable")


def evaluate(root, symbol, session_dates, thresholds, as_of, execution="shares", journal="verified"):
    """Screen each requested session using only its immediately preceding 20 sessions.

    The 80% summary applies only to the caller-supplied research window. Callers
    must not use future test-window eligibility to choose an earlier universe.
    """
    if execution not in ("shares", "options"):
        raise ValueError("execution must be shares or options")
    if not isinstance(thresholds, dict):
        raise ValueError("Explicit liquidity thresholds are required")
    required = ["min_share_volume", "max_share_spread_bps"]
    if execution == "options":
        required += ["min_options_volume", "max_options_spread_bps"]
    policy = {name: _number(thresholds.get(name), name) for name in required}
    for name in ("min_options_volume", "max_options_spread_bps"):
        if name in thresholds:
            policy[name] = _number(thresholds[name], name)
    symbol, cutoff = _symbol(symbol), utc(as_of)
    dates = list(session_dates)
    for day in dates:
        _day(day)
    if not dates or len(set(dates)) != len(dates):
        raise ValueError("A nonempty, unique research-session window is required")
    result = {"schema_version": VERSION, "symbol": symbol, "execution": execution, "journal": journal,
              "as_of": cutoff.isoformat(), "window_sessions": WINDOW, "required_fraction": REQUIRED_FRACTION,
              "thresholds": policy, "spread_aggregation": "median_of_session_medians",
              "metric_methods": {"volumes": "mean_of_20_prior_complete_exchange_sessions",
                                 "spreads": "median_of_session_medians; not pooled quote median"},
              "research_eligible": False, "eligible_fraction": 0., "session_results": [], "reasons": [],
              "execution_qualified": False}
    try:
        rows = {key: row for key, row in _load(root, journal).items() if utc(row["available_at"]) <= cutoff}
    except (ValueError, OSError, KeyError, TypeError, RuntimeError) as exc:
        return {**result, "status": "data_blocked", "reasons": [str(exc)]}
    for day in sorted(dates):
        share_reasons, option_reasons, metrics, history, decision = [], [], {}, [], None
        try:
            bounds = session(_day(day).isoformat())
            if not bounds.get("is_session") or not bounds.get("calendar_verified"):
                raise ValueError("Target session is outside verified exchange-calendar coverage")
            decision = min(utc(bounds["open"]), cutoff)
            history = [rows.get((symbol, prior)) for prior in _prior(day)]
            history = [row if row is not None and utc(row["available_at"]) <= decision else None for row in history]
            if any(row is None or not row["complete_session"] for row in history):
                raise ValueError("Missing, partial or not-yet-available preceding session aggregates")
            for name in METRICS:
                values = [row[name] for row in history]
                metrics[name] = None if any(v is None for v in values) else (
                    math.fsum(v / WINDOW for v in values) if name.endswith("volume") else
                    sorted(values)[WINDOW // 2 - 1] / 2 + sorted(values)[WINDOW // 2] / 2)
            for metric, threshold, maximum in (("share_volume", "min_share_volume", False),
                                                ("share_median_spread_bps", "max_share_spread_bps", True)):
                value = metrics[metric]
                if value is None or (value > policy[threshold] if maximum else value < policy[threshold]):
                    share_reasons.append(metric + " missing or outside policy")
            for metric, threshold, maximum in (("options_volume", "min_options_volume", False),
                                                ("options_median_spread_bps", "max_options_spread_bps", True)):
                value = metrics[metric]
                if threshold not in policy or value is None or (value > policy[threshold] if maximum else value < policy[threshold]):
                    option_reasons.append(metric + " missing, unchecked or outside policy")
        except (ValueError, KeyError, TypeError, OverflowError) as exc:
            share_reasons.append(str(exc))
        selected = share_reasons + (option_reasons if execution == "options" else [])
        result["session_results"].append({"session_date": day, "research_eligible": not selected,
            "share_eligible": not share_reasons, "options_eligible": not (share_reasons + option_reasons),
            "decision_cutoff": decision.isoformat() if decision is not None else None,
            "input_sessions": history, "metrics": metrics, "reasons": selected})
    result["eligible_fraction"] = sum(row["research_eligible"] for row in result["session_results"]) / len(dates)
    result["research_eligible"] = result["eligible_fraction"] >= REQUIRED_FRACTION
    for track in ("share", "options"):
        fraction = sum(row[track + "_eligible"] for row in result["session_results"]) / len(dates)
        result[track + "_eligible_fraction"] = fraction
        result[track + "_eligible"] = fraction >= REQUIRED_FRACTION
    result["status"] = "eligible" if result["research_eligible"] else "ineligible" if rows else "unavailable"
    if not result["research_eligible"]:
        result["reasons"] = ["Fewer than 80% of requested sessions pass the causal liquidity policy"]
    return result
