"""One id per trading opportunity, shared by the stance log, the paper book, calls and journal notes.

Review B6 (2026-11-18; user: "Yes, go ahead"). An opportunity is one registered rule firing on one ETF at one
close, for one entry policy, under one evidence export:
    "<close>:<ETF>:<rule>:<policy>:<first 12 of the export's sha256>"
e.g. "2026-11-17:QQQ:rsi2_below_10:next_open:793a58bd49ec". It is derived from fields the logs already keep, so
the same id comes out wherever it is computed. Only records written from 2026-11-18 on carry it; older records in
the append-only logs stay exactly as written (their ids can still be derived from their fields).

What each log says about an opportunity:
- Stance record ("opportunities"): the page's disposition: "long" (its next-open pricing is a Lead), "abstain:
  closing-price Lead only", "abstain: forward below band" or "abstain: no Lead". A close with no stance recorded
  before its next open gets a "missed" stance record, written afterwards and labelled so.
- Call ("opportunity_ids", "relation"), from the stance record for the call's close and the ETF's index (UPRO and
  SPXU are SPY views, TQQQ and SQQQ QQQ views; the inverse ones flip the direction): "take" (the page was long and
  so is the call), "veto" (the page was long, the call is flat or short), "override" (the page abstained on a
  fired rule and the call is long), "agree flat" (a flat call and no long), "own view" (anything else, or an ETF
  the page doesn't log), "unlinked" (no stance recorded for that close yet).
- Journal note ("opportunity_ids"): the opportunities at the close the page showed when the note was saved.
- Paper book trade ("opportunity_id"): computed for each trade.
"""
from __future__ import annotations

from . import eligibility

POLICY = "next_open"
LOGGED = ("SPY", "QQQ")  # the ETFs the stance log covers
UNDERLYING = {"SPY": ("SPY", 1), "UPRO": ("SPY", 1), "SPXU": ("SPY", -1),
              "QQQ": ("QQQ", 1), "TQQQ": ("QQQ", 1), "SQQQ": ("QQQ", -1), "IWM": ("IWM", 1)}


def oid(day: str, symbol: str, rule: str, policy: str = POLICY, evidence: str | None = None) -> str:
    return f"{day}:{symbol}:{rule}:{policy}:{(evidence or 'none')[:12]}"


def for_signals(signals: list[dict], symbol: str, day: str, evidence: str | None) -> list[dict]:
    """The opportunities at `day`'s close on `symbol`, with the page's disposition (stance rules v2)."""
    out = []
    for s in signals or []:
        if s.get("symbol") != symbol or not s.get("fired"):
            continue
        if eligibility.open_leads(s):
            disposition = "long"
        elif eligibility.forward_below(s):
            disposition = "abstain: forward below band"
        elif eligibility.close_only_leads(s):
            disposition = "abstain: closing-price Lead only"
        else:
            disposition = "abstain: no Lead"
        out.append({"id": oid(day, symbol, s["signal"], POLICY, evidence), "rule": s["signal"], "policy": POLICY,
                    "disposition": disposition})
    return out


def of_record(record: dict) -> list[dict]:
    """A stance record's opportunities: stored on new records, derived from the rule lists on older ones."""
    if record.get("opportunities") is not None:
        return record["opportunities"]
    day, symbol, evidence = record.get("latest_close"), record.get("instrument"), record.get("evidence_sha256")
    return ([{"id": oid(day, symbol, r, POLICY, evidence), "rule": r, "policy": POLICY, "disposition": "long"}
             for r in record.get("rules") or []]
            + [{"id": oid(day, symbol, r, POLICY, evidence), "rule": r, "policy": POLICY,
                "disposition": "abstain: closing-price Lead only"} for r in record.get("close_only_rules") or []])


def link_call(stance_rows: list[dict], call: dict) -> dict:
    """How a new call relates to the page's opportunities at its close."""
    latest = (call.get("context") or {}).get("latest_close")
    underlying, sign = UNDERLYING.get(call["instrument"], (call["instrument"], 1))
    view = {"long": 1, "short": -1, "flat": 0}[call["direction"]] * sign
    if underlying not in LOGGED:
        return {"opportunity_ids": [], "relation": "own view"}
    record = next((r for r in stance_rows if r.get("latest_close") == latest and r.get("instrument") == underlying
                   and r.get("direction") != "missed"), None) if latest else None
    if record is None:
        return {"opportunity_ids": [], "relation": "unlinked"}
    opportunities = of_record(record)
    if record.get("direction") == "long":
        relation = "take" if view > 0 else "veto"
    elif view > 0 and opportunities:
        relation = "override"
    elif view == 0:
        relation = "agree flat"
    else:
        relation = "own view"
    return {"opportunity_ids": [o["id"] for o in opportunities], "relation": relation}


def link_note(stance_rows: list[dict], latest: str | None, instrument: str | None) -> list[str]:
    """Opportunity ids at the close a journal note's page showed (the note's ETF's index, or both if none)."""
    if not latest:
        return []
    wanted = {UNDERLYING.get(instrument, (instrument, 1))[0]} if instrument else set(LOGGED)
    return [o["id"] for r in stance_rows if r.get("latest_close") == latest and r.get("instrument") in wanted
            for o in of_record(r)]
