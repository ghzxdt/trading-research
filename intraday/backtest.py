"""One preregistered intraday shares baseline. Bar fills are scenarios, not evidence of fills.

One position per complete session; first qualifying 15-minute ORB cross confirmed
by typical-price VWAP; opposite ORB boundary stop; 2R target; scheduled flatten.
No grid search, option proxy, leverage recommendation, or journal writes.
"""
from __future__ import annotations
import math
import numpy as np
import pandas as pd
from .calendar import utc, date_of, session
from .store import canonical, digest
from .features import STUDY_ID, PARAMETERS, in_regular, complete_grid, candidate, vwap_points, orb_state

DEFAULT_CONFIG = {"half_spread_bps": 1.0, "slippage_bps_per_side": 2.0,
                  "fee_bps_per_side": 0.0, "latency_seconds": 1,
                  "flatten_minutes_before_close": 5,
                  "assume_bar_close_availability": False}


def configuration(config):
    supplied = dict(config or {})
    unknown = set(supplied) - set(DEFAULT_CONFIG)
    if unknown:
        raise ValueError("Unknown baseline configuration fields: " + ", ".join(sorted(unknown)))
    c = {**DEFAULT_CONFIG, **supplied}
    if not isinstance(c["assume_bar_close_availability"], bool):
        raise ValueError("assume_bar_close_availability must be boolean")
    for name in ("half_spread_bps", "slippage_bps_per_side", "fee_bps_per_side"):
        c[name] = float(c[name])
        if not math.isfinite(c[name]) or not 0 <= c[name] <= 1000:
            raise ValueError("Cost assumptions must be finite, nonnegative and at most 1000 bp per component")
    for name, minimum, maximum in (("latency_seconds", 1, 600), ("flatten_minutes_before_close", 1, 60)):
        value = c[name]
        if isinstance(value, bool) or not float(value).is_integer() or not minimum <= int(value) <= maximum:
            raise ValueError(f"Invalid {name}")
        c[name] = int(value)
    return c


def pnl(entry, exit_reference, side, c):
    drag = (c["half_spread_bps"] + c["slippage_bps_per_side"]) / 10000
    entry_fill = entry * (1 + side * drag)
    exit_fill = exit_reference * (1 - side * drag)
    gross = side * (exit_reference / entry - 1)
    price_return = side * (exit_fill - entry_fill) / entry_fill
    fees = c["fee_bps_per_side"] / 10000 * (1 + exit_fill / entry_fill)
    return {"entry_fill": entry_fill, "exit_fill": exit_fill, "gross_return": gross,
            "net_return": price_return - fees, "fees_return": fees,
            "execution_drag_return": gross - price_return}


def uncertainty(session_returns):
    values = np.asarray([r["net_return"] for r in session_returns], dtype=float)
    if len(values) < 20:
        return {"status": "insufficient_sessions", "independent_units": "sessions", "sessions": len(values),
                "mean_session_return_95ci": None, "method": "Session bootstrap; minimum 20 complete sessions"}
    rng = np.random.default_rng(20261108)
    draws = rng.choice(values, size=(2000, len(values)), replace=True).mean(axis=1)
    return {"status": "exploratory", "independent_units": "sessions", "sessions": len(values),
            "mean_session_return_95ci": [float(v) for v in np.quantile(draws, [.025, .975])],
            "method": "2000 session bootstrap draws; sessions assumed exchangeable; not proof of an edge"}


def run(records, config=None):
    c = configuration(config)
    raw = canonical(records)
    symbols = {r["symbol"] for r in raw}
    if len(symbols) > 1:
        raise ValueError("Run each symbol separately; pooled ticker optimization is not implemented")
    if any(r["interval_seconds"] != 60 for r in raw):
        raise ValueError("The frozen ORB baseline requires one-minute bars")
    rows = []
    for row in raw:
        item = dict(row)
        if c["assume_bar_close_availability"]:
            item["available_at"] = (utc(item["timestamp"]) + pd.Timedelta(minutes=1)).isoformat()
        rows.append(item)
    dates = sorted({date_of(r["timestamp"]) for r in rows})
    trades, sessions, exclusions, no_trades = [], [], [], []
    for date in dates:
        bounds = session(date)
        if not bounds.get("is_session") or not bounds.get("calendar_verified"):
            exclusions.append({"session": date, "reason": "Non-session or unverified intraday exchange calendar"})
            continue
        opening, closing = utc(bounds["open"]), utc(bounds["close"])
        flatten = closing - pd.Timedelta(minutes=c["flatten_minutes_before_close"])
        day = [r for r in rows if date_of(r["timestamp"]) == date and in_regular(r, bounds)]
        # Include the flatten-open bar: it supplies a future observable exit event.
        required_end = flatten + pd.Timedelta(minutes=1)
        required = [r for r in day if utc(r["timestamp"]) < required_end]
        coverage = complete_grid(required, opening, required_end)
        if not coverage["complete"]:
            exclusions.append({"session": date, "reason": "Incomplete minute path through planned flatten; no result scored", "coverage": coverage})
            continue
        if not required:
            continue
        points = vwap_points(required)
        latest_at_knowledge, newest_start = {}, None
        for published in sorted(required, key=lambda r: (utc(r["available_at"]), utc(r["timestamp"]))):
            published_start = utc(published["timestamp"])
            newest_start = max(newest_start, published_start) if newest_start is not None else published_start
            latest_at_knowledge[utc(published["available_at"])] = newest_start
        opening_rows = required[:15]
        orb = orb_state(opening_rows, bounds, max(utc(r["available_at"]) for r in opening_rows))
        if not orb["complete"]:
            exclusions.append({"session": date, "reason": "Opening range unavailable"})
            continue
        prefix_known, signal = opening, None
        for i, row in enumerate(required):
            start, known = utc(row["timestamp"]), utc(row["available_at"])
            prefix_known = max(prefix_known, known)
            if start < opening + pd.Timedelta(minutes=15) or start >= flatten:
                continue
            # Every input to the prefix VWAP/ORB must have been published at the
            # candidate's knowledge timestamp; late corrections cannot leak back.
            if prefix_known > known or max(utc(r["available_at"]) for r in opening_rows) > known:
                continue
            # A backfilled cross is not a new signal if a later completed bar was
            # already known then. Reject stale publication even without a newer
            # observation; a halted/delayed feed cannot revive an old crossing.
            if latest_at_knowledge[known] != start or known - (start + pd.Timedelta(minutes=1)) > pd.Timedelta(seconds=120):
                continue
            trial = candidate(required[:i + 1], orb, points[:i + 1])
            if trial["state"] == "candidate" and known + pd.Timedelta(seconds=c["latency_seconds"]) < flatten:
                trial["index"] = i
                signal = trial
                break
        if signal is None:
            sessions.append({"session": date, "net_return": 0., "traded": False})
            no_trades.append({"session": date, "reason": "No causal qualifying ORB crossing before flatten"})
            continue
        threshold = utc(signal["known_at"]) + pd.Timedelta(seconds=c["latency_seconds"])
        entry_index = next((i for i, r in enumerate(required)
                            if i > signal["index"] and utc(r["timestamp"]) >= threshold and utc(r["timestamp"]) < flatten), None)
        if entry_index is None:
            sessions.append({"session": date, "net_return": 0., "traded": False})
            no_trades.append({"session": date, "reason": "No observed entry event after signal availability and latency"})
            continue
        entry_row = required[entry_index]
        entry, side, stop = entry_row["open"], signal["side"], signal["stop_level"]
        risk = side * (entry - stop)
        if risk <= 0:
            sessions.append({"session": date, "net_return": 0., "traded": False})
            no_trades.append({"session": date, "reason": "Entry gapped through signal invalidation; skipped"})
            continue
        target = entry + side * 2 * risk
        if target <= 0:
            sessions.append({"session": date, "net_return": 0., "traded": False})
            no_trades.append({"session": date, "reason": "Observed entry gap makes the fixed 2R target nonpositive; no valid share-price target"})
            continue
        exit_reference, exit_at, reason, ambiguous = None, None, None, False
        for row in required[entry_index:]:
            start = utc(row["timestamp"])
            if start >= flatten:
                exit_reference, exit_at, reason = row["open"], start.isoformat(), "scheduled_flatten"
                break
            stop_gap = row["open"] <= stop if side == 1 else row["open"] >= stop
            target_gap = row["open"] >= target if side == 1 else row["open"] <= target
            hit_stop = row["low"] <= stop if side == 1 else row["high"] >= stop
            hit_target = row["high"] >= target if side == 1 else row["low"] <= target
            if stop_gap:
                exit_reference, reason = row["open"], "stop_gap"
            elif target_gap:
                exit_reference, reason = target, "target_gap_at_limit"
            elif hit_stop:
                exit_reference, reason, ambiguous = stop, "stop", bool(hit_target)
            elif hit_target:
                exit_reference, reason = target, "target"
            if exit_reference is not None:
                # Bar data do not locate the touch within the minute.
                exit_at = (start + pd.Timedelta(minutes=1)).isoformat()
                break
        if exit_reference is None:
            exclusions.append({"session": date, "reason": "No observable flatten event; trade unresolved and not scored"})
            continue
        result = pnl(entry, exit_reference, side, c)
        trade = {"symbol": next(iter(symbols)), "session": date, "study_id": STUDY_ID,
                 "signal_bar": signal["signal_bar"], "signal_known_at": signal["known_at"],
                 "entry_at": entry_row["timestamp"], "exit_at": exit_at,
                 "side": side, "entry_reference": entry, "exit_reference": exit_reference,
                 "stop_level": stop, "target_level": target, "exit_reason": reason,
                 "ambiguous_bar_stop_first": ambiguous, "planned_risk_per_share": risk,
                 "net_r_multiple": result["net_return"] * result["entry_fill"] / risk,
                 "fill_model": "OHLC next-event scenario; actual quotes and capacity unknown", **result}
        trades.append(trade)
        sessions.append({"session": date, "net_return": result["net_return"], "traded": True})
    outcomes = np.asarray([t["net_return"] for t in trades], dtype=float)
    daily = np.asarray([s["net_return"] for s in sessions], dtype=float)
    insolvent = bool(np.any(daily <= -1))
    wealth = np.cumprod(1 + daily) if len(daily) and not insolvent else np.array([])
    peaks = np.maximum.accumulate(np.r_[1., wealth])
    drawdown = np.r_[1., wealth] / peaks - 1 if len(wealth) else np.array([])
    losses = -outcomes[outcomes < 0].sum() if len(outcomes) else 0.
    metrics = {"complete_sessions": len(sessions), "excluded_sessions": len(exclusions), "trades": len(trades),
               "no_trade_sessions": len(no_trades), "mean_trade_return": float(outcomes.mean()) if len(outcomes) else None,
               "win_rate": float((outcomes > 0).mean()) if len(outcomes) else None,
               "profit_factor": float(outcomes[outcomes > 0].sum() / losses) if losses else None,
               "scenario_compounded_return": float(wealth[-1] - 1) if len(wealth) else None,
               "scenario_max_drawdown": float(drawdown.min()) if len(drawdown) else None,
               "compounding_status": "insolvent_path_suppressed" if insolvent else "scenario_only" if len(daily) else "no_scored_sessions",
               "insolvency_session": next((s["session"] for s in sessions if s["net_return"] <= -1), None),
               "mean_session_return": float(daily.mean()) if len(daily) else None,
               "session_sharpe": float(daily.mean() / daily.std(ddof=1) * np.sqrt(252)) if not insolvent and len(daily) >= 20 and daily.std(ddof=1) > 0 else None,
               "ambiguous_bar_trades": sum(t["ambiguous_bar_stop_first"] for t in trades), "edge_validated": False}
    limitations = ["Single registered shares baseline; no strategy search or demonstrated edge.",
                   "Bar-derived fill scenarios use assumed costs; no executable quotes, capacity, borrow or stop-fill guarantees.",
                   "One position per session; no leveraged sizing or account recommendation.",
                   "Incomplete sessions are explicitly excluded, not scored as zero; exclusions may bias available-history results.",
                   "A short feed archive is development data, not an untouched holdout; no gamma/option-chain claim is made.",
                   "Bootstrap groups observations by session; serial dependence across sessions remains a limitation.",
                   "Verified early-close calendar covers cash-equity sessions in 2025–2028 only."]
    if insolvent:
        limitations.insert(0, "A session loss reaches or exceeds 100% of entry notional. Compounded account metrics and Sharpe are suppressed; financing, margin and insolvency are not calibrated.")
    if c["assume_bar_close_availability"]:
        limitations.insert(0, "ASSUMED TIMING SCENARIO: historical bars are assumed available at bar end. Actual archive receipt times are not contemporaneous observations; these results cannot qualify as forward evidence.")
    else:
        limitations.insert(0, "Actual supplied available_at timestamps are respected. Backfilled archives may produce no historical signals.")
    return {"schema_version": 1, "symbol": next(iter(symbols), None),
            "study": {"id": STUDY_ID, "parameters": dict(PARAMETERS), "config_hash": digest(c), "registered_variants": 1,
                      "evidence_status": "historical_scenario", "forward_eligible": False},
            "config": c, "metrics": metrics, "trades": trades, "session_returns": sessions,
            "uncertainty": uncertainty(sessions), "exclusions": exclusions, "abstentions": no_trades,
            "quality": {"input_bars": len(raw), "sessions_seen": len(dates), "availability_bases": sorted({r["availability_basis"] for r in raw}),
                        "scoring_status": "no_complete_sessions" if not sessions else "exploratory_scenario"},
            "limitations": limitations}
