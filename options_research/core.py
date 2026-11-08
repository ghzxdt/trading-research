"""Causal contract data, observed concentrations and executable-price scenarios.

Imports must supply source timestamps and actual contract definitions. Receipt
time is not automatically an exchange quote timestamp. Open interest is not
signed dealer inventory. No output here establishes a profitable strategy.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone, date
from hashlib import sha256
import csv
import json
import math
import os
from pathlib import Path
import re
from statistics import median
from zoneinfo import ZoneInfo

UTC = timezone.utc
NY = ZoneInfo("America/New_York")
SCHEMA_VERSION = 1
RELATIVE_STORE = Path("data/options_research/events.jsonl")


def _dt(value=None):
    if value is None:
        return datetime.now(UTC)
    result = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("Options timestamps require an explicit timezone.")
    return result.astimezone(UTC)


def _num(value, name, optional=False, minimum=None):
    if value is None or value == "":
        if optional:
            return None
        raise ValueError(f"Missing {name}.")
    if isinstance(value, bool):
        raise ValueError(f"Invalid {name}.")
    result = float(value)
    if not math.isfinite(result) or (minimum is not None and result < minimum):
        raise ValueError(f"Invalid {name}.")
    return result


def _integer(value, name, optional=False, minimum=0):
    result = _num(value, name, optional, minimum)
    if result is not None and result != int(result):
        raise ValueError(f"{name} must be an integer.")
    return None if result is None else int(result)


def normalize(record):
    row = dict(record)
    symbol = str(row.get("symbol") or row.get("underlying") or "").strip().upper()
    contract, source = str(row.get("contract_id") or "").strip(), str(row.get("source") or "").strip()
    if not symbol or not contract or not source:
        raise ValueError("symbol, contract_id and source are required.")
    if not re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,14}", symbol):
        raise ValueError("Invalid options underlying symbol.")
    right = str(row.get("right") or "").upper()
    right = {"CALL": "C", "PUT": "P"}.get(right, right)
    if right not in {"C", "P"}:
        raise ValueError("right must be C/call or P/put.")
    expiry = date.fromisoformat(str(row.get("expiry", "")))
    if not row.get("timestamp") or not row.get("available_at"):
        raise ValueError("Source timestamp and actual availability time are required.")
    stamp, available = _dt(row["timestamp"]), _dt(row["available_at"])
    if available < stamp:
        raise ValueError("available_at cannot precede the quote timestamp.")
    strike = _num(row.get("strike"), "strike", minimum=.0000001)
    multiplier = _num(row.get("multiplier"), "multiplier", minimum=.0000001)
    adjusted = row.get("adjusted", False)
    if isinstance(adjusted, str):
        adjusted = adjusted.strip().lower()
        if adjusted not in {"true", "1", "yes", "false", "0", "no", ""}:
            raise ValueError("adjusted must be an explicit boolean.")
        adjusted = adjusted in {"true", "1", "yes"}
    elif not isinstance(adjusted, bool):
        raise ValueError("adjusted must be an explicit boolean.")
    deliverable = str(row.get("deliverable") or "").strip()
    if adjusted and not deliverable:
        raise ValueError("Adjusted contracts require their actual deliverable.")
    quality = row.get("quality") or []
    if isinstance(quality, str):
        quality = [quality] if quality else []
    if not isinstance(quality, list):
        raise ValueError("quality must be a list of source flags.")
    out = {"schema_version": SCHEMA_VERSION, "symbol": symbol, "underlying": symbol,
           "contract_id": contract, "expiry": expiry.isoformat(), "right": right,
           "strike": strike, "multiplier": multiplier, "adjusted": bool(adjusted),
           "deliverable": deliverable or "Unadjusted contract; multiplier supplied by source",
           "timestamp": stamp.isoformat(), "available_at": available.isoformat(),
           "source": source, "quality": [str(v) for v in quality]}
    for name in ("bid", "ask", "iv", "gamma"):
        out[name] = _num(row.get(name), name, True, 0)
    for name in ("bid_size", "ask_size", "open_interest", "volume"):
        out[name] = _integer(row.get(name), name, True)
    out["delta"] = _num(row.get("delta"), "delta", True)
    if out["delta"] is not None and not -1 <= out["delta"] <= 1:
        raise ValueError("delta must use units between -1 and 1.")
    if out["iv"] is not None and out["iv"] > 10:
        raise ValueError("iv must be decimal annualized volatility, not percentage points.")
    if out["bid"] is None or out["ask"] is None:
        out["quality"].append("quote_missing")
    elif out["ask"] <= 0 or out["bid"] > out["ask"]:
        out["quality"].append("quote_invalid")
    out["expiration_at"] = None
    if row.get("expiration_at"):
        expiration = _dt(row["expiration_at"])
        if expiration.astimezone(NY).date() != expiry:
            raise ValueError("expiration_at must agree with expiry in market time.")
        out["expiration_at"] = expiration.isoformat()
    out.update(open_interest_as_of=None, oi_available_at=None)
    if out["open_interest"] is not None:
        if row.get("open_interest_as_of") and row.get("oi_available_at"):
            oi_day, oi_available = date.fromisoformat(str(row["open_interest_as_of"])), _dt(row["oi_available_at"])
            if oi_day > oi_available.astimezone(NY).date():
                raise ValueError("OI observation date is after its availability.")
            out.update(open_interest_as_of=oi_day.isoformat(), oi_available_at=oi_available.isoformat())
        else:
            out["quality"].append("oi_availability_unknown")
    out["quality"] = sorted(set(out["quality"]))
    return out


def _digest(obj):
    return sha256(json.dumps(obj, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _events(path):
    if not path.exists():
        return []
    result, previous = [], ""
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        event = json.loads(line)
        payload = {k: v for k, v in event.items() if k != "hash"}
        if event.get("previous_hash") != previous or event.get("hash") != _digest(payload):
            raise ValueError("Options store hash chain failed; store was not modified.")
        previous = event["hash"]
        result.append(event)
    return result


@contextmanager
def _writer(path):
    lock, descriptor = path.with_suffix(path.suffix + ".lock"), None
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(descriptor, str(os.getpid()).encode())
        yield
    except FileExistsError as exc:
        raise RuntimeError("Another options import is writing; retry after it completes.") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
            lock.unlink(missing_ok=True)


def ingest(root, records):
    """Validate the complete batch, then append only new observations."""
    if os.environ.get("APP_REPLAY") == "1" or os.environ.get("APP_OFFLINE") == "1":
        raise ValueError("Offline/replay mode cannot append options observations.")
    rows = [normalize(record) for record in records]
    path = Path(root) / RELATIVE_STORE
    path.parent.mkdir(parents=True, exist_ok=True)
    inserted = 0
    with _writer(path):
        events = _events(path)
        versions = {}
        for row in [event["record"] for event in events] + rows:
            version = (row["contract_id"], row["timestamp"], row["available_at"])
            if version in versions and versions[version] != row:
                raise ValueError("Conflicting contract observations share the same source and availability timestamps.")
            versions[version] = row
        identities = {event["observation_id"] for event in events}
        previous, pending = events[-1]["hash"] if events else "", []
        for row in rows:
            identity = _digest(row)
            if identity in identities:
                continue
            payload = {"schema_version": 1, "type": "option_observation", "observation_id": identity,
                       "record": row, "ingested_at": datetime.now(UTC).isoformat(), "previous_hash": previous}
            event = {**payload, "hash": _digest(payload)}
            pending.append(json.dumps(event, sort_keys=True, allow_nan=False) + "\n")
            previous = event["hash"]
            identities.add(identity)
            inserted += 1
        if pending:
            with path.open("a", encoding="utf-8", newline="\n") as stream:
                stream.writelines(pending)
                stream.flush()
                os.fsync(stream.fileno())
    return {"status": "imported", "inserted": inserted, "duplicates": len(rows) - inserted,
            "path": RELATIVE_STORE.as_posix(), "schema_version": 1}


def import_file(root, path):
    """Explicit JSON/CSV import. Validation and replay protection remain identical."""
    path = Path(path)
    if path.suffix.lower() == ".csv":
        with path.open(encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.DictReader(stream))
        for row in rows:
            if row.get("quality", "").lstrip().startswith("["):
                row["quality"] = json.loads(row["quality"])
    elif path.suffix.lower() in {".json", ".jsonl"}:
        if path.suffix.lower() == ".jsonl":
            rows = [json.loads(line) for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
        else:
            value = json.loads(path.read_text(encoding="utf-8-sig"))
            rows = value.get("records") if isinstance(value, dict) else value
        if not isinstance(rows, list):
            raise ValueError("JSON input must contain a list or a records list.")
    else:
        raise ValueError("Options import supports .csv, .json and .jsonl files.")
    return ingest(root, rows)


def history(root, symbol, as_of=None):
    cutoff, symbol = _dt(as_of), str(symbol).upper()
    rows = [event["record"] for event in _events(Path(root) / RELATIVE_STORE)
            if event["record"]["symbol"] == symbol and _dt(event["record"]["available_at"]) <= cutoff]
    return sorted(rows, key=lambda row: (row["available_at"], row["timestamp"], row["contract_id"]))


def _latest(records, as_of):
    cutoff, selected = _dt(as_of), {}
    for record in records:
        row = normalize(record)
        if _dt(row["available_at"]) > cutoff or _dt(row["timestamp"]) > cutoff:
            continue
        previous = selected.get(row["contract_id"])
        order = lambda item: (_dt(item["timestamp"]), _dt(item["available_at"]))
        if previous is not None and order(row) == order(previous) and row != previous:
            raise ValueError("Conflicting contract observations require a distinct actual revision timestamp.")
        if previous is None or order(row) > order(previous):
            selected[row["contract_id"]] = row
    return sorted(selected.values(), key=lambda row: (row["expiry"], row["strike"], row["right"], row["contract_id"]))


def load(root, symbol, as_of=None):
    """Latest knowledge-available observation per contract; never double-count OI."""
    return _latest(history(root, symbol, as_of), as_of)


def _expired(row, cutoff):
    if row.get("expiration_at"):
        return _dt(row["expiration_at"]) <= cutoff
    return date.fromisoformat(row["expiry"]) < cutoff.astimezone(NY).date()


def _quote_problems(row, cutoff, quantity=1, max_age=60, max_spread=.15):
    reasons = []
    if _dt(row["available_at"]) > cutoff or _dt(row["timestamp"]) > cutoff:
        reasons.append("Quote was unavailable at the decision time.")
    if (cutoff - _dt(row["timestamp"])).total_seconds() > max_age:
        reasons.append("Quote exceeds the configured maximum age.")
    blocking = set(row["quality"]) - {"oi_availability_unknown"}
    if blocking:
        reasons.append("Source quality flags: " + ", ".join(sorted(blocking)))
    if _expired(row, cutoff):
        reasons.append("Contract is expired.")
    if row["expiry"] == cutoff.astimezone(NY).date().isoformat() and not row.get("expiration_at"):
        reasons.append("Same-day expiry requires an explicit instrument cutoff.")
    if row["adjusted"]:
        reasons.append("Adjusted deliverables require a product-specific execution adapter.")
    bid, ask = row["bid"], row["ask"]
    if bid is None or ask is None or ask <= 0 or bid < 0 or bid > ask:
        reasons.append("A valid two-sided quote is unavailable.")
    elif (ask - bid) / ((ask + bid) / 2) > max_spread:
        reasons.append("Spread exceeds the configured fraction of option midpoint.")
    if row["ask_size"] is None or row["bid_size"] is None:
        reasons.append("Quoted sizes are unavailable.")
    elif min(row["ask_size"], row["bid_size"]) < quantity:
        reasons.append("Displayed size does not cover the requested contracts.")
    return reasons


def summarize(records, spot=None, as_of=None):
    cutoff = _dt(as_of)
    rows = [row for row in _latest(records, cutoff) if not _expired(row, cutoff)]
    if len({row["symbol"] for row in rows}) > 1:
        raise ValueError("Summarize one underlying at a time; cross-market level scaling must be explicit.")
    spot = _num(spot, "spot", True, .0000001)
    groups, levels = {}, []
    for row in rows:
        group = groups.setdefault(row["expiry"], {"expiry": row["expiry"], "contracts": 0,
                  "call_open_interest": 0, "put_open_interest": 0, "known_oi_contracts": 0})
        group["contracts"] += 1
        oi = row["open_interest"] if row.get("oi_available_at") and _dt(row["oi_available_at"]) <= cutoff else None
        if oi is None:
            continue
        group["known_oi_contracts"] += 1
        group["call_open_interest" if row["right"] == "C" else "put_open_interest"] += oi
        if oi <= 0:
            continue
        unsigned = row["gamma"] * oi * row["multiplier"] if row["gamma"] is not None else None
        dollars = unsigned * spot * spot * .01 if unsigned is not None and spot else None
        known = max(_dt(row["available_at"]), _dt(row["oi_available_at"])).isoformat()
        levels.append({"id": "option-" + _digest({k: row[k] for k in ("contract_id", "timestamp", "oi_available_at")})[:16],
                       "price": row["strike"], "type": "open_interest_concentration",
                       "label": f"{row['expiry']} {row['right']} strike concentration",
                       "source": row["source"], "source_market": row["symbol"], "contract_ids": [row["contract_id"]],
                       "expiry": row["expiry"], "right": row["right"], "open_interest": oi,
                       "open_interest_as_of": row["open_interest_as_of"], "knowledge_time": known,
                       "detected_at": row["available_at"], "valid_from": known,
                       "expires_at": row.get("expiration_at"), "expiry_date": row["expiry"],
                       "invalidation": "Superseded source snapshot or contract expiration; no inferred price barrier.",
                       "method_version": "observed-oi-concentration-v1", "behavior": "unvalidated",
                       "unsigned_gamma_shares_per_dollar": unsigned, "unsigned_dollar_gamma_per_one_percent": dollars,
                       "dealer_gamma_scenarios": None if dollars is None else {"assume_all_long": dollars, "assume_all_short": -dollars},
                       "distance_pct": row["strike"] / spot - 1 if spot else None,
                       "quote_age_seconds": max(0, (cutoff - _dt(row["timestamp"])).total_seconds()),
                       "oi_age_calendar_days": (cutoff.astimezone(NY).date() - date.fromisoformat(row["open_interest_as_of"])).days,
                       "quality": row["quality"],
                       "assumptions": "Observed concentration. Dealer-sign scenarios are assumptions, not measured inventory."})
    levels.sort(key=lambda level: (-level["open_interest"], abs(level["distance_pct"] or 0), level["id"]))
    iv = []
    if spot:
        for expiry in sorted(groups):
            nearest = sorted([r for r in rows if r["expiry"] == expiry and r["iv"] is not None],
                             key=lambda r: (abs(r["strike"] / spot - 1), r["contract_id"]))[:4]
            if nearest:
                iv.append({"expiry": expiry, "near_spot_iv_median": median(r["iv"] for r in nearest),
                           "source_contracts": [r["contract_id"] for r in nearest], "quote_times": [r["timestamp"] for r in nearest],
                           "method": "Up to four nearest quoted strikes; pricing context, not a physical forecast."})
    latest_quote = max((_dt(row["timestamp"]) for row in rows), default=None)
    return {"schema_version": 1, "status": "observed_context" if rows else "unavailable", "as_of": cutoff.isoformat(),
            "contracts": len(rows), "expiries": list(groups.values()), "levels": levels[:20], "iv_context": iv,
            "quote_health": {"latest_quote_at": latest_quote.isoformat() if latest_quote else None,
                             "latest_quote_age_seconds": (cutoff - latest_quote).total_seconds() if latest_quote else None,
                             "execution_qualified_contracts": sum(not _quote_problems(row, cutoff) for row in rows),
                             "qualification_rule": "60-second age, displayed sizes and at most 15% midpoint spread; configurable in expression selection."},
            "dealer_positioning": "unknown", "validated_level_edge": False,
            "limitations": ["Strike concentrations are hypotheses, not established support/resistance.",
                            "OI has its own availability lag and does not identify signed dealer inventory.",
                            "Import verified contract observations; this module supplies no historical execution dataset."]}


def select_expression(records, direction, account=None, as_of=None):
    """Select by a declared rule before affordability; feasibility is not alpha."""
    cutoff, account = _dt(as_of), dict(account or {})
    direction = str(direction).lower()
    right = "C" if direction in {"1", "long", "bullish", "up", "call"} else "P" if direction in {"-1", "short", "bearish", "down", "put"} else None
    base = {"schema_version": 1, "as_of": cutoff.isoformat(), "sizing_allowed": False, "strategy_validated": False, "quantity": None}
    if right is None:
        return {**base, "status": "no_trade", "reasons": ["No directional hypothesis was supplied."]}
    quantity = _integer(account.get("quantity", 1), "quantity", minimum=1)
    max_age = _num(account.get("max_quote_age_seconds", 60), "max_quote_age_seconds", minimum=0)
    max_spread = _num(account.get("max_spread_pct", .15), "max_spread_pct", minimum=0)
    fee = _num(account.get("fee_per_contract_per_side", 0), "fee_per_contract_per_side", minimum=0)
    min_dte, max_dte = _integer(account.get("min_dte", 1), "min_dte"), _integer(account.get("max_dte", 7), "max_dte")
    target_delta = _num(account.get("target_abs_delta", .5), "target_abs_delta", minimum=0)
    if not 0 < target_delta <= 1 or max_dte < min_dte:
        raise ValueError("Invalid contract-selection parameters.")
    matches, rejected = [], []
    rows = _latest(records, cutoff)
    if len({row["symbol"] for row in rows}) > 1:
        raise ValueError("Select an expression for one underlying at a time.")
    for row in rows:
        dte = (date.fromisoformat(row["expiry"]) - cutoff.astimezone(NY).date()).days
        if row["right"] != right or not min_dte <= dte <= max_dte:
            continue
        problems = _quote_problems(row, cutoff, quantity, max_age, max_spread)
        if row["delta"] is None:
            problems.append("Delta missing for the declared delta-based selection rule.")
        elif (right == "C" and row["delta"] < 0) or (right == "P" and row["delta"] > 0):
            problems.append("Delta sign is inconsistent with the contract right.")
        if problems:
            rejected.extend(problems)
            continue
        debit = row["ask"] * row["multiplier"] * quantity + fee * quantity
        matches.append((abs(abs(row["delta"]) - target_delta), dte, row["contract_id"], row, debit))
    rule = {"right": right, "target_abs_delta": target_delta, "min_dte": min_dte, "max_dte": max_dte,
            "budget_reselection": False, "dte_units": "calendar days"}
    if not matches:
        return {**base, "status": "unavailable", "reasons": sorted(set(rejected)) or ["No eligible contracts in the declared expiry range."], "selection_rule": rule}
    _, _, _, row, debit = min(matches, key=lambda item: item[:3])
    planned_loss = debit + fee * quantity
    result = {**base, "instrument": "long_call" if right == "C" else "long_put", "contract": row,
              "debit": debit, "max_loss": planned_loss, "reserved_close_fee": fee * quantity,
              "premium_at_risk": row["ask"] * row["multiplier"] * quantity, "comparison_quantity": quantity,
              "spread_dollars_per_contract": (row["ask"] - row["bid"]) * row["multiplier"], "selection_rule": rule,
              "fee_per_contract_per_side": fee, "fee_assumption_supplied": "fee_per_contract_per_side" in account,
              "risk_note": "Risk reserves full premium plus entry/closing fees and assumes no unwanted exercise-created stock position."}
    budgets = [(key, _num(account.get(key), key, True, 0)) for key in ("max_trade_debit", "max_loss_per_trade", "available_cash")]
    breaches = [f"Selected expression exceeds {key}." for key, value in budgets
                if value is not None and (planned_loss if key in {"max_loss_per_trade", "available_cash"} else debit) > value]
    if account.get("options_permitted") is False:
        breaches.append("Account is not configured to permit options.")
    if breaches:
        return {**result, "status": "no_feasible_expression", "reasons": breaches}
    missing = [f"Configure {key}." for key, value in budgets if value is None]
    if account.get("options_permitted") is not True:
        missing.append("Confirm account options permissions.")
    if "fee_per_contract_per_side" not in account:
        missing.append("Configure the applicable per-contract fee assumption.")
    if missing:
        return {**result, "status": "candidate", "reasons": missing}
    return {**result, "status": "eligible", "quantity": quantity,
            "reasons": ["Quote/account feasibility only; recommended sizing still requires strategy evidence and an approved risk policy."]}


def _pair(entry, exit, quantity):
    quantity = _integer(quantity, "quantity", minimum=1)
    a, b = normalize(entry), normalize(exit)
    identity = ("contract_id", "symbol", "right", "strike", "expiry", "multiplier", "deliverable", "adjusted")
    if any(a[key] != b[key] for key in identity):
        raise ValueError("Entry/exit must refer to the same contract and deliverable.")
    if _dt(b["timestamp"]) < _dt(a["available_at"]) or _dt(b["available_at"]) < _dt(a["available_at"]):
        raise ValueError("Exit cannot precede entry.")
    for row in (a, b):
        if row["adjusted"]:
            raise ValueError("Adjusted contracts need a product-specific deliverable adapter.")
        if row["bid"] is None or row["ask"] is None or not 0 <= row["bid"] <= row["ask"] or row["ask"] <= 0:
            raise ValueError("P&L requires valid two-sided quotes.")
        if set(row["quality"]) - {"oi_availability_unknown"}:
            raise ValueError("P&L requires quality-qualified source quotes.")
        if (_dt(row["available_at"]) - _dt(row["timestamp"])).total_seconds() > 60:
            raise ValueError("P&L quote receipt is more than 60 seconds after the quote.")
        if _expired(row, _dt(row["available_at"])):
            raise ValueError("P&L cannot execute an expired option.")
        if row["expiry"] == _dt(row["available_at"]).astimezone(NY).date().isoformat() and not row.get("expiration_at"):
            raise ValueError("Same-day execution requires an explicit expiration cutoff.")
    if a["ask_size"] is None or b["bid_size"] is None or min(a["ask_size"], b["bid_size"]) < quantity:
        raise ValueError("Displayed size does not support full entry/exit.")
    return a, b, quantity


def executable_pnl(entry, exit, quantity=1, fees=0):
    """Buy entry ask, sell exit bid. fees is per contract per side."""
    a, b, quantity = _pair(entry, exit, quantity)
    fee, units = _num(fees, "fees", minimum=0), quantity * a["multiplier"]
    gross, charges = (b["bid"] - a["ask"]) * units, 2 * quantity * fee
    debit = a["ask"] * units + quantity * fee
    return {"status": "quoted_scenario", "entry_fill": a["ask"], "exit_fill": b["bid"],
            "quantity": quantity, "multiplier": a["multiplier"], "debit": debit, "gross_pnl": gross,
            "fees": charges, "net_pnl": gross - charges, "return_on_debit": (gross - charges) / debit,
            "planned_loss_with_close_fees": debit + quantity * fee,
            "extra_theta_deduction": 0,
            "assumptions": "Full displayed-size marketable fills; queue priority and additional execution latency are not certified."}


def debit_spread_pnl(entry_long, entry_short, exit_long, exit_short, quantity=1, fees=0, max_sync_seconds=1):
    long_a, long_b, quantity = _pair(entry_long, exit_long, quantity)
    short_a, short_b, _ = _pair(entry_short, exit_short, quantity)
    for key in ("symbol", "expiry", "right", "multiplier", "deliverable", "adjusted"):
        if long_a[key] != short_a[key]:
            raise ValueError("A vertical requires matching underlying, expiry, right and deliverable.")
    if (long_a["right"] == "C" and long_a["strike"] >= short_a["strike"]) or (long_a["right"] == "P" and long_a["strike"] <= short_a["strike"]):
        raise ValueError("Debit vertical strike order is invalid.")
    sync = _num(max_sync_seconds, "max_sync_seconds", minimum=0)
    for a, b in ((long_a, short_a), (long_b, short_b)):
        if abs((_dt(a["timestamp"]) - _dt(b["timestamp"])).total_seconds()) > sync or abs((_dt(a["available_at"]) - _dt(b["available_at"])).total_seconds()) > sync:
            raise ValueError("Spread leg quotes are not synchronized.")
    entry_known = max(_dt(long_a["available_at"]), _dt(short_a["available_at"]))
    if min(_dt(long_b["timestamp"]), _dt(short_b["timestamp"])) < entry_known:
        raise ValueError("Spread exit quotes cannot precede availability of the complete entry.")
    if short_a["bid_size"] is None or short_b["ask_size"] is None or min(short_a["bid_size"], short_b["ask_size"]) < quantity:
        raise ValueError("Short-leg size does not support the spread.")
    fee, units = _num(fees, "fees", minimum=0), quantity * long_a["multiplier"]
    premium, width = long_a["ask"] - short_a["bid"], abs(long_a["strike"] - short_a["strike"])
    if not 0 < premium < width:
        raise ValueError("Entry quotes do not produce a debit below spread width.")
    credit, charges = long_b["bid"] - short_b["ask"], quantity * fee * 4
    debit = premium * units + quantity * fee * 2
    pnl = (credit - premium) * units - charges
    return {"status": "quoted_spread_scenario", "quantity": quantity, "entry_debit_per_unit": premium,
            "exit_credit_per_unit": credit, "debit": debit, "fees": charges, "net_pnl": pnl,
            "return_on_debit": pnl / debit, "bounded_payoff_max_loss": debit, "extra_theta_deduction": 0,
            "planned_loss_with_close_fees": debit + quantity * fee * 2,
            "assumptions": "Intact vertical closed with synchronized full-size quotes. Assignment, legging and temporary stock exposure are not simulated; bounded payoff does not guarantee execution or account cash requirements."}


def price_scenarios(contract, spot, scenarios, as_of=None, rate=0, dividend_yield=0):
    """Joint European theoretical sensitivities, never executable backtest returns."""
    row, cutoff = normalize(contract), _dt(as_of)
    spot, rate, dividend_yield = _num(spot, "spot", minimum=.0000001), _num(rate, "rate"), _num(dividend_yield, "dividend_yield")
    if row["iv"] is None or row["iv"] <= 0 or not row.get("expiration_at"):
        return {"status": "unavailable", "reasons": ["Scenarios require decimal IV and an explicit expiration timestamp."]}
    if _dt(row["available_at"]) > cutoff:
        return {"status": "unavailable", "reasons": ["Contract observation is not available yet."]}
    if _dt(row["expiration_at"]) <= cutoff:
        return {"status": "unavailable", "reasons": ["The contract has expired; a later spot cannot reprice its settled payoff."]}
    seconds = max(0, (_dt(row["expiration_at"]) - cutoff).total_seconds())
    cdf = lambda value: .5 * (1 + math.erf(value / math.sqrt(2)))
    def price(s, vol, remaining):
        if remaining <= 0:
            return max(s - row["strike"], 0) if row["right"] == "C" else max(row["strike"] - s, 0)
        t = remaining / (365.25 * 86400)
        d1 = (math.log(s / row["strike"]) + (rate - dividend_yield + .5 * vol * vol) * t) / (vol * math.sqrt(t))
        d2 = d1 - vol * math.sqrt(t)
        if row["right"] == "C":
            return s * math.exp(-dividend_yield * t) * cdf(d1) - row["strike"] * math.exp(-rate * t) * cdf(d2)
        return row["strike"] * math.exp(-rate * t) * cdf(-d2) - s * math.exp(-dividend_yield * t) * cdf(-d1)
    baseline, output = price(spot, row["iv"], seconds), []
    for item in scenarios:
        move, shift = _num(item.get("spot_change_pct", 0), "spot_change_pct"), _num(item.get("iv_change", 0), "iv_change")
        elapsed = _num(item.get("elapsed_minutes", 0), "elapsed_minutes", minimum=0)
        if elapsed * 60 > seconds:
            raise ValueError("A scenario cannot use a post-expiration spot as the settlement price.")
        s, vol = spot * (1 + move), row["iv"] + shift
        if not math.isfinite(s) or not math.isfinite(vol) or s <= 0 or not 0 < vol <= 10:
            raise ValueError("Scenario spot and IV must stay positive.")
        value = price(s, vol, max(0, seconds - elapsed * 60))
        output.append({"label": str(item.get("label") or "Scenario"), "spot_change_pct": move, "iv_change": shift,
                       "elapsed_minutes": elapsed, "theoretical_premium": value,
                       "theoretical_change_per_contract": (value - baseline) * row["multiplier"], "probability": None})
    return {"status": "theoretical_only", "model": "European Black-Scholes; constant input rates and scenario IV",
            "base_theoretical_premium": baseline, "scenarios": output,
            "limitations": ["American exercise, discrete dividends, surface dynamics and executable spreads are not modeled.",
                            "Scenarios have no real-world probability or validated trade expectancy."]}
