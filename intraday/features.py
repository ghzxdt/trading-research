"""Causal chart features and one registered ORB continuation research candidate."""
from __future__ import annotations
import pandas as pd
from validation import equity_sessions
from .calendar import utc, date_of, session, NY
from .store import canonical, digest

BAD_PRINT = 0.01  # an extended-hours print more than 1% from the surrounding closes is treated as a bad print
STUDY_ID = "orb-continuation-v1"
PARAMETERS = {"opening_range_minutes": 15, "target_r": 2.0, "max_trades_per_session": 1,
              "vwap_confirmation": True, "direction": "both", "entry": "next_event_after_knowledge_and_latency"}


def in_regular(row, bounds):
    if not bounds.get("is_session"):
        return False
    start = utc(row["timestamp"])
    return (utc(bounds["open"]) <= start and
            start + pd.Timedelta(seconds=row["interval_seconds"]) <= utc(bounds["close"]))


def complete_grid(rows, start, end, seconds=60):
    expected = pd.date_range(utc(start), utc(end), freq=f"{seconds}s", inclusive="left")
    present = {utc(r["timestamp"]) for r in rows if r["interval_seconds"] == seconds}
    missing = [t.isoformat() for t in expected if t not in present]
    return {"complete": not missing, "expected_bars": len(expected), "observed_bars": len(expected) - len(missing),
            "missing_bars": len(missing), "missing_examples": missing[:5]}


def vwap_points(rows):
    numerator, denominator, points, known = 0., 0., [], None
    for row in rows:
        numerator += (row["high"] + row["low"] + row["close"]) / 3 * row["volume"]
        denominator += row["volume"]
        known = max(known, utc(row["available_at"])) if known is not None else utc(row["available_at"])
        points.append({"time": int(utc(row["timestamp"]).timestamp()),
                       "value": numerator / denominator if denominator else None,
                       "available_at": known.isoformat()})
    return points


def orb_state(rows, bounds, as_of):
    if not bounds.get("is_session"):
        return {"complete": False, "high": None, "low": None, "reason": "Not a cash-equity session"}
    start = utc(bounds["open"])
    end = start + pd.Timedelta(minutes=15)
    opening = [r for r in rows if start <= utc(r["timestamp"]) < end]
    coverage = complete_grid(opening, start, end)
    ready = coverage["complete"] and utc(as_of) >= end
    return {"complete": ready, "high": max(r["high"] for r in opening) if ready else None,
            "low": min(r["low"] for r in opening) if ready else None,
            "start": start.isoformat(), "end": end.isoformat(),
            "available_at": max((r["available_at"] for r in opening), default=None) if ready else None,
            "coverage": coverage, "reason": "Completed 15-minute range" if ready else "Opening range incomplete"}


def candidate(rows, orb, vwap):
    abstain = {"state": "abstain", "side": 0, "study_id": STUDY_ID}
    if not orb.get("complete") or len(rows) < 2:
        return {**abstain, "reason": "A complete opening range and subsequent bar are required"}
    prior, current = rows[-2:]
    if utc(current["timestamp"]) < utc(orb["end"]):
        return {**abstain, "reason": "Opening range is still forming"}
    if not vwap or vwap[-1]["value"] is None:
        return {**abstain, "reason": "VWAP unavailable because observed volume is zero"}
    value = vwap[-1]["value"]
    side = (1 if prior["close"] <= orb["high"] < current["close"] and current["close"] > value else
            -1 if prior["close"] >= orb["low"] > current["close"] and current["close"] < value else 0)
    if not side or orb["high"] <= orb["low"]:
        return {**abstain, "reason": "No new opening-range crossing with VWAP confirmation"}
    return {"state": "candidate", "side": side, "study_id": STUDY_ID,
            "reason": "Completed-bar ORB crossing with session VWAP confirmation; execution is a separate next-event scenario",
            "signal_bar": current["timestamp"], "known_at": current["available_at"],
            "entry_trigger": "First observed bar open strictly after signal availability plus configured latency",
            "reference_price": current["close"], "stop_level": orb["low"] if side == 1 else orb["high"],
            "target_r": 2.0, "validated_edge": False}


def snapshot(records, as_of):
    cutoff = utc(as_of)
    rows = canonical(records, cutoff)
    symbols = {r["symbol"] for r in rows}
    if len(symbols) > 1:
        raise ValueError("A feature snapshot requires exactly one symbol")
    market_bounds = session(date_of(cutoff))
    observed_dates = sorted({date_of(r["timestamp"]) for r in rows})
    displayed_date = market_bounds["date"] if market_bounds["date"] in observed_dates else (observed_dates[-1] if observed_dates else market_bounds["date"])
    bounds = session(displayed_date)
    symbol = next(iter(symbols), None)
    current = [r for r in rows if date_of(r["timestamp"]) == bounds["date"]]
    regular = [r for r in current if in_regular(r, bounds)]
    regular = sorted(regular, key=lambda r: r["timestamp"])
    reasons = []
    if displayed_date != market_bounds["date"]:
        reasons.append("Displaying a previous session; no current-session observations are available")
    if not bounds.get("is_session"):
        reasons.append("Not a cash-equity session")
    if not bounds.get("calendar_verified"):
        reasons.append("Intraday exchange hours outside verified 2025–2028 calendar")
    if any(r["interval_seconds"] != 60 for r in current):
        reasons.append("Registered baseline requires one-minute bars")
    coverage = {"complete": False, "missing_bars": 0}
    if regular:
        coverage = complete_grid(regular, bounds["open"], utc(regular[-1]["timestamp"]) + pd.Timedelta(minutes=1))
        if not coverage["complete"]:
            reasons.append("Missing regular-session minutes; features are descriptive only")
    else:
        reasons.append("No completed regular-session bars known at this cutoff")
    points = vwap_points(regular)
    orb = orb_state(regular, bounds, cutoff)
    latest_end = (utc(regular[-1]["timestamp"]) + pd.Timedelta(seconds=regular[-1]["interval_seconds"])) if regular else None
    lag = max(0., (cutoff - latest_end).total_seconds()) if latest_end is not None else None
    if lag is not None and lag > 120 and bounds.get("is_session") and cutoff < utc(bounds["close"]):
        reasons.append("Latest completed bar is stale by more than 120 seconds")
    if bounds.get("is_session") and cutoff >= utc(bounds["close"]):
        reasons.append("Cash-equity session closed")
    signal = candidate(regular, orb, points)
    if reasons:
        signal = {"state": "abstain", "side": 0, "study_id": STUDY_ID, "reason": "; ".join(reasons)}
    display_day = pd.Timestamp(bounds["date"])
    preceding = equity_sessions(display_day - pd.Timedelta(days=14), display_day - pd.Timedelta(days=1))
    previous_date = preceding[-1].strftime("%Y-%m-%d") if len(preceding) else None
    prior = None
    if previous_date:
        prior_bounds = session(previous_date)
        prior_rows = [r for r in rows if date_of(r["timestamp"]) == previous_date and in_regular(r, prior_bounds)]
        if prior_rows:
            prior_coverage = complete_grid(prior_rows, prior_bounds["open"], prior_bounds["close"])
            prior = {"session": previous_date, "complete": prior_coverage["complete"],
                     "high": max(r["high"] for r in prior_rows) if prior_coverage["complete"] else None,
                     "low": min(r["low"] for r in prior_rows) if prior_coverage["complete"] else None,
                     "close": prior_rows[-1]["close"] if prior_coverage["complete"] else None,
                     "available_at": max(r["available_at"] for r in prior_rows), "coverage": prior_coverage}
    overnight = []
    if bounds.get("is_session"):
        prior_close = utc(session(previous_date)["close"]) if previous_date else utc(bounds["open"]) - pd.Timedelta(days=1)
        overnight = [r for r in rows if prior_close <= utc(r["timestamp"]) < utc(bounds["open"])]
    # Extended-hours feeds carry occasional bad prints (seen 2026-11-11: SPY "traded" 711.46 between 760.04 and
    # 760.08, as the bar's open and low). A high or low more than BAD_PRINT away from both that bar's close and
    # the previous bar's close is a spike that reverted within the minute: it is replaced by the nearer of those
    # two closes, and counted, so one stray tick can't set a level.
    ordered = sorted(overnight, key=lambda r: r["timestamp"])
    highs, lows, suspect = [], [], 0
    for i, r in enumerate(ordered):
        closes = [r["close"]] + ([ordered[i - 1]["close"]] if i else [])
        top, bottom = max(closes), min(closes)
        bad_high, bad_low = r["high"] > top * (1 + BAD_PRINT), r["low"] < bottom * (1 - BAD_PRINT)
        suspect += bad_high or bad_low
        highs.append(top if bad_high else r["high"])
        lows.append(bottom if bad_low else r["low"])
    levels = {"prior_session": prior,
              "overnight_observed": {"high": max(highs), "low": min(lows),
                                     "bars": len(overnight), "coverage_verified": False, "suspect_prints_excluded": suspect,
                                     "label": "Observed extended-hours range; feed coverage may be incomplete"
                                              + (f"; {suspect} suspect print(s) excluded" if suspect else "")} if overnight else None,
              "orb_high": orb.get("high"), "orb_low": orb.get("low")}
    forward = bool(regular) and all(r["availability_basis"] == "observed_live" for r in regular)
    return {"schema_version": 1, "symbol": symbol, "as_of": cutoff.isoformat(), "session": bounds, "market_session": market_bounds,
            "snapshot_id": digest({"as_of": cutoff.isoformat(), "bars": rows}),
            "quality": {"status": "ready" if not reasons and orb["complete"] else "insufficient_data",
                        "reasons": reasons, "coverage": coverage, "bar_lag_seconds": lag,
                        "forward_eligible": forward and not reasons,
                        "availability_bases": sorted({r["availability_basis"] for r in rows}),
                        "edge_validated": False},
            "bars": [{**r, "time": int(utc(r["timestamp"]).timestamp())} for r in current[-1200:]],
            "vwap": points, "orb": orb, "levels": levels, "signal": signal,
            "limitations": ["OHLCV does not contain executable bid/ask or option chains.",
                            "VWAP uses bar typical price, not individual trades.",
                            "ORB is a preregistered research baseline, not a demonstrated edge."]}
