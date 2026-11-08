"""Frozen, pre-touch level diagnostics. These are not simulated trade fills."""
from __future__ import annotations

from collections import defaultdict
from datetime import timedelta
import math
import random
from statistics import mean

from .core import _dt, _num, _integer, NY

DEFAULTS = {"tolerance_pct": .0005, "rejection_pct": .001,
            "breakout_pct": .001, "horizon_minutes": 20}


def evaluate_levels(levels, bars, config=None, as_of=None):
    """First observed touch per level/session; competing bar outcomes unscored.

Level definitions must be known before the touch bar starts. The touch bar's
interior is deliberately not ordered using its final OHLC. Reaction evaluation
starts on the next bar. All outcome parameters are explicit and returned.
"""
    cfg = {**DEFAULTS, **(config or {})}
    for key in ("tolerance_pct", "rejection_pct", "breakout_pct"):
        cfg[key] = _num(cfg[key], key, minimum=.00000001)
    cfg["horizon_minutes"] = _integer(cfg["horizon_minutes"], "horizon_minutes", minimum=1)
    cutoff = _dt(as_of)
    rows = []
    for item in bars:
        row = dict(item)
        stamp, available = _dt(row["timestamp"]), _dt(row["available_at"])
        if available > cutoff or stamp > cutoff:
            continue
        row.update(timestamp=stamp, available_at=available)
        for key in ("open", "high", "low", "close"):
            row[key] = _num(row.get(key), key, minimum=.0000001)
        if not row["low"] <= min(row["open"], row["close"]) <= max(row["open"], row["close"]) <= row["high"]:
            raise ValueError("Invalid OHLC range in level diagnostic.")
        row["interval_seconds"] = _integer(row.get("interval_seconds", 60), "interval_seconds", minimum=1)
        if available < stamp + timedelta(seconds=row["interval_seconds"]):
            raise ValueError("Completed bars cannot be known before their interval ends.")
        row["session"] = stamp.astimezone(NY).date().isoformat()
        rows.append(row)
    rows.sort(key=lambda row: (row["timestamp"], row["available_at"]))
    symbols = {str(row["symbol"]).upper() for row in rows if row.get("symbol")}
    if len(symbols) > 1:
        raise ValueError("Level diagnostics require bars from a single source market.")
    if len({row["timestamp"] for row in rows}) != len(rows):
        raise ValueError("Level diagnostics require one observation per bar timestamp.")
    # Historical snapshots of the same contract concentration supersede one
    # another. Keeping every version alive would multiply one reaction into
    # many observations and use stale features after a source update.
    superseded_at, lifecycles = {}, defaultdict(list)
    for index, item in enumerate(levels):
        if item.get("contract_ids"):
            lifecycle = (str(item.get("source_market")), str(item.get("source")),
                         str(item.get("method_version")), tuple(sorted(map(str, item["contract_ids"]))))
            known = item.get("knowledge_time") or item.get("valid_from")
            if known:
                lifecycles[lifecycle].append((_dt(known), index))
    for versions in lifecycles.values():
        versions.sort()
        if len({known for known, _ in versions}) != len(versions):
            raise ValueError("Contract-level lifecycle versions require distinct knowledge timestamps.")
        for (_, index), (next_known, _) in zip(versions, versions[1:]):
            superseded_at[index] = next_known
    output = []
    for number, item in enumerate(levels):
        level = dict(item)
        if level.get("source_market") and symbols and str(level["source_market"]).upper() not in symbols:
            raise ValueError("A level cannot be rescaled to another market implicitly.")
        level_id = str(level.get("id") or f"level-{number}")
        price = _num(level.get("price"), "level price", minimum=.0000001)
        known_value = level.get("knowledge_time") or level.get("valid_from")
        if not known_value:
            raise ValueError("Every evaluated level requires its pre-touch knowledge timestamp.")
        known = _dt(known_value)
        expiration = _dt(level["expires_at"]) if level.get("expires_at") else None
        if level.get("valid_until"):
            expiration = min(expiration, _dt(level["valid_until"])) if expiration else _dt(level["valid_until"])
        if number in superseded_at:
            expiration = min(expiration, superseded_at[number]) if expiration else superseded_at[number]
        expiry_day = level.get("expiry_date") or level.get("expiry")
        seen = set()
        for i in range(1, len(rows)):
            row, prior = rows[i], rows[i - 1]
            session = row["session"]
            if session in seen or prior["session"] != session or known >= row["timestamp"]:
                continue
            if expiration and row["timestamp"] >= expiration:
                continue
            if expiry_day and session > str(expiry_day):
                continue
            if prior["available_at"] > row["timestamp"]:
                continue
            if prior["timestamp"] + timedelta(seconds=prior["interval_seconds"]) != row["timestamp"]:
                continue
            tolerance = price * cfg["tolerance_pct"]
            if not row["low"] <= price + tolerance or not row["high"] >= price - tolerance:
                continue
            if abs(prior["close"] - price) <= tolerance:
                continue
            seen.add(session)
            approach = "from_below" if prior["close"] < price else "from_above"
            touch_end = row["timestamp"] + timedelta(seconds=row["interval_seconds"])
            if expiration and touch_end > expiration:
                continue
            original_deadline = touch_end + timedelta(minutes=cfg["horizon_minutes"])
            deadline = original_deadline
            if expiration:
                deadline = min(deadline, expiration)
            outcome, outcome_at = "censored", None
            future = [r for r in rows[i + 1:] if r["session"] == session and touch_end <= r["timestamp"] and
                      r["timestamp"] + timedelta(seconds=r["interval_seconds"]) <= deadline]
            last_end, gap = touch_end, False
            favorable, adverse = 0., 0.
            for later in future:
                if later["timestamp"] > last_end:
                    gap = True
                    break
                last_end = later["timestamp"] + timedelta(seconds=later["interval_seconds"])
                if approach == "from_below":
                    reject = later["low"] <= price * (1 - cfg["rejection_pct"])
                    breakout = later["high"] >= price * (1 + cfg["breakout_pct"])
                    favorable = max(favorable, (price - later["low"]) / price)
                    adverse = max(adverse, (later["high"] - price) / price)
                else:
                    reject = later["high"] >= price * (1 + cfg["rejection_pct"])
                    breakout = later["low"] <= price * (1 - cfg["breakout_pct"])
                    favorable = max(favorable, (later["high"] - price) / price)
                    adverse = max(adverse, (price - later["low"]) / price)
                if reject or breakout:
                    outcome = "ambiguous_unscored" if reject and breakout else "rejection" if reject else "breakout"
                    outcome_at = later["available_at"].isoformat()
                    break
            if outcome == "censored" and not gap and last_end >= deadline and cutoff >= deadline:
                outcome = "censored_by_invalidation" if deadline < original_deadline else "unresolved"
            output.append({"level_id": level_id, "matched_to": level.get("matched_to"),
                           "session": session, "level_price": price, "source": level.get("source"),
                           "knowledge_time": known.isoformat(), "touch_at": row["timestamp"].isoformat(),
                           "effective_valid_until": expiration.isoformat() if expiration else None,
                           "touch_bar_unscored": True, "deadline": deadline.isoformat(), "approach": approach,
                           "requested_deadline": original_deadline.isoformat(),
                           "outcome": outcome, "outcome_at": outcome_at,
                           "max_rejection_excursion_pct": favorable, "max_breakout_excursion_pct": adverse,
                           "data_gap": gap})
    return {"schema_version": 1, "status": "descriptive_diagnostic", "config": cfg,
            "as_of": cutoff.isoformat(), "observations": output,
            "limitations": ["Reaction labels are not trade fills or net expectancy.",
                            "First observed touch requires a separate coverage check before it can be called the session's first actual touch.",
                            "First touches within a session are still dependent; infer at session level.",
                            "Levels, control matching and parameters must be registered before evaluation."]}


def _interval(values, seed=719, draws=2000):
    if len(values) < 3:
        return None
    rng = random.Random(seed)
    samples = sorted(mean(rng.choices(values, k=len(values))) for _ in range(draws))
    return [samples[int(.025 * draws)], samples[min(draws - 1, int(.975 * draws))]]


def level_study(option_levels, control_levels, bars, config=None, as_of=None):
    """Compare frozen levels with explicitly matched controls at session level.

Each control must name matched_to=<option level id>. Matching variables are a
caller responsibility and must be recorded in the preregistered study config.
This function never certifies matching or treats touches as independent trades.
"""
    options = evaluate_levels(option_levels, bars, config, as_of)
    controls = evaluate_levels(control_levels, bars, config, as_of)
    groups = {"options": defaultdict(list), "controls": defaultdict(list)}
    ids = {str(level["id"]) for level in option_levels if level.get("id")}
    controls_matched = bool(control_levels) and all(level.get("matched_to") and str(level["matched_to"]) in ids for level in control_levels)
    for key, result in (("options", options), ("controls", controls)):
        for observation in result["observations"]:
            if observation["outcome"] in {"rejection", "breakout"}:
                groups[key][observation["session"]].append(1. if observation["outcome"] == "rejection" else 0.)
    def describe(key):
        means = [mean(values) for _, values in sorted(groups[key].items())]
        source = options if key == "options" else controls
        counts = defaultdict(int)
        for observation in source["observations"]:
            counts[observation["outcome"]] += 1
        return {"sessions": len(means), "resolved_touches": sum(len(v) for v in groups[key].values()),
                "all_observed_touches": len(source["observations"]), "outcome_counts": dict(counts),
                "conditional_on_resolved_touches": True,
                "session_mean_rejection_rate": mean(means) if means else None,
                "session_bootstrap_95_interval": _interval(means)}
    common = sorted(set(groups["options"]) & set(groups["controls"]))
    difference = [mean(groups["options"][day]) - mean(groups["controls"][day]) for day in common] if controls_matched else []
    return {"schema_version": 1, "status": "descriptive_diagnostic", "config": options["config"],
            "options": describe("options"), "controls": describe("controls"),
            "explicit_control_links_present": controls_matched, "paired_sessions": len(difference),
            "paired_session_rejection_difference": mean(difference) if difference else None,
            "paired_session_bootstrap_95_interval": _interval(difference),
            "validated_edge": False,
            "limitations": ["Caller must verify controls match distance, round numbers, volatility, time of day and expiry.",
                            "Bootstrap intervals are exploratory; no untouched holdout or multiplicity correction is created.",
                            "A reaction-rate difference does not establish after-cost profitability."]}
