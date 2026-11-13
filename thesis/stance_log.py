"""The page's own daily stance, logged forward and scored the same way as the user's calls.

Rules fixed 2026-11-08 (user asked for the page's stance to be scored like their calls):
- Online builds (the evening refresh, or a manual online refresh) append one record per evidence ETF (SPY, QQQ)
  for the latest close: long when a rule the backtester rated Lead fired on that ETF, flat otherwise.
- Forward only. Nothing is backfilled; testing the past is the backtester's job.
- Logged only while the entry is still ahead: before 9:30 AM ET on the session after the stance's close. A later
  refresh skips that close instead of recording a stale stance.
- Skipped when the backtester's evidence is missing or a rule's definition no longer matches it, so a "flat"
  never really means "evidence unavailable".
- Stance rules v2 (2026-11-13, records carry "stance_rules": 2; earlier records are v1 and stay as written):
  long needs a rule whose *next-open* pricing is a Lead, the entry the record is scored from. Under v1 any Lead
  pricing counted, including "buy at the signal close", which had passed by the time the stance was logged.
  Rules that fired with only a closing-price Lead are kept in "close_only_rules" and the record is flat.
- One record per ETF per close; the first one stands (append-only, hash-chained, never edited by hand).
- Scored like a call: from the next session's open to the close 5 sessions later (a fixed horizon declared here,
  not the rule's own exit), against simply holding the ETF over the same days.
Offline and replay builds never write.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from . import calls, eligibility
from .data import NY

LOG = Path("data/thesis/stance_log.jsonl")
HORIZON = 5
SYMBOLS = ("SPY", "QQQ")


def records_for(state: dict) -> tuple[list[dict], str | None]:
    """The records an online build would log, or the reason nothing is logged. Uses the same check as the page
    (thesis/eligibility.py): the evidence must be usable, and a rule counts only with a next-open Lead."""
    check = state.get("evidence_check") or eligibility.evidence_check(
        state.get("evidence_source"), state.get("signals", []), state.get("latest_close"), SYMBOLS)
    if not check.get("usable"):
        return [], check.get("reason") or "the backtester's evidence is unavailable"
    signals = [s for s in state.get("signals", []) if s.get("symbol") in SYMBOLS]
    out = []
    for symbol in SYMBOLS:
        mine = [s for s in signals if s["symbol"] == symbol]
        leads = [s["signal"] for s in mine if s["fired"] and eligibility.open_leads(s)]
        passed = [s["signal"] for s in mine if s["fired"] and eligibility.close_only_leads(s)]
        exits = {s["signal"]: sorted({e["exit"] for e in eligibility.open_leads(s)}) for s in mine if s["signal"] in leads}
        out.append({"instrument": symbol, "direction": "long" if leads else "flat", "rules": leads,
                    "close_only_rules": passed, "rule_exits": exits})  # exits: what the paper book follows
    return out, None


def append_daily(root: Path, state: dict, now: pd.Timestamp, entry_time=None) -> dict:
    """Append today's stance records if they're new and their entry is still ahead; say why otherwise."""
    if entry_time is None:
        from refresh_guard import entry_time
    latest = state.get("latest_close")
    if not latest:
        return {"logged": 0, "skipped": "no latest close"}
    deadline = entry_time(pd.Timestamp(latest))
    if now >= deadline:
        return {"logged": 0, "skipped": f"too late: the {latest} stance's entry ({deadline:%Y-%m-%d %H:%M} ET) has passed"}
    records, reason = records_for(state)
    if reason:
        return {"logged": 0, "skipped": reason}
    rows = calls.read(root, LOG)
    done = {(r["latest_close"], r["instrument"]) for r in rows}
    path = Path(root) / LOG
    previous = rows[-1]["hash"] if rows else ""
    logged = 0
    for record in records:
        if (latest, record["instrument"]) in done:
            continue
        body = {"schema": 1, "id": len(rows) + logged + 1, "source": "page",
                "recorded_utc": now.tz_convert("UTC").isoformat(timespec="seconds"),
                "recorded_et": now.tz_convert(NY).isoformat(timespec="seconds"), "latest_close": latest,
                **record, "stance_rules": eligibility.RULES_VERSION, "horizon_sessions": HORIZON, "headline": (state.get("stance") or {}).get("headline"),
                "evidence_sha256": (state.get("evidence_source") or {}).get("sha256"), "previous_hash": previous}
        row = {**body, "hash": calls._digest(body)}
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n")
        previous, logged = row["hash"], logged + 1
    return {"logged": logged, "skipped": None if logged else f"the {latest} stance was already logged"}


def summary(root: Path, etfs: dict) -> dict:
    check = calls.verify(root, LOG)
    if not check["ok"]:
        return {"status": "broken", "reason": check["reason"], "records": [], "scoreboard": calls.scoreboard([])}
    rows = calls.read(root, LOG)
    scored = []
    for row in rows:
        result = calls.score(row, etfs.get(row["instrument"]))
        scored.append({**result, "latest_close": row["latest_close"], "rules": row.get("rules", []),
                       "close_only_rules": row.get("close_only_rules", []), "stance_rules": row.get("stance_rules", 1)})
    by_symbol = {s: calls.scoreboard([x for x in scored if x["instrument"] == s]) for s in SYMBOLS}
    longs = [x for x in scored if x["direction"] == "long" and x.get("status") == "scored"]
    board = calls.scoreboard(scored)
    board["note"] = ("One record per ETF per close, each scored over the next 5 sessions from the next open, so "
                     "neighbouring days overlap and are not independent. Flat scores 0. Before costs, unlevered.")
    return {"status": "ok", "horizon_sessions": HORIZON, "first_close": rows[0]["latest_close"] if rows else None,
            "scoreboard": board, "by_symbol": by_symbol, "long_scored": len(longs),
            "long_mean": sum(x["call_return"] for x in longs) / len(longs) if longs else None,
            "records": list(reversed(scored))[:20]}
