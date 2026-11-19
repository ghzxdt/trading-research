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
  Since 2026-11-18 (backtester Lead v3) a fired rule whose next-open verdict is "Forward below band" is kept in
  "forward_below_rules" and the record is flat; the rules themselves are unchanged (only "Lead" counts).
- One record per ETF per close; the first one stands (append-only, hash-chained, never edited by hand).
- Scored like a call: from the next session's open to the close 5 sessions later (a fixed horizon declared here,
  not the rule's own exit), against simply holding the ETF over the same days. Since 2026-11-18 a long record is
  also scored to its rule's own exit ("rule_exit"), as the backtester prices it; the fixed horizon stays.
Offline and replay builds never write.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from . import calls, eligibility, opportunity
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
        # Lead v3 (2026-11-18): fired, but demoted from Lead by its forward record, so it doesn't make the record long.
        demoted = [s["signal"] for s in mine if s["fired"] and not eligibility.open_leads(s) and eligibility.forward_below(s)]
        exits = {s["signal"]: sorted({e["exit"] for e in eligibility.open_leads(s)}) for s in mine if s["signal"] in leads}
        # Review B6 (2026-11-18): each fired rule as an opportunity with the page's disposition.
        found = opportunity.for_signals(mine, symbol, state.get("latest_close"), (state.get("evidence_source") or {}).get("sha256"))
        out.append({"instrument": symbol, "direction": "long" if leads else "flat", "rules": leads,
                    "close_only_rules": passed, "forward_below_rules": demoted, "opportunities": found,
                    "rule_exits": exits})  # exits: what the paper book follows
    return out, None


def append_daily(root: Path, state: dict, now: pd.Timestamp, entry_time=None) -> dict:
    """Append today's stance records if they're new and their entry is still ahead; say why otherwise."""
    if entry_time is None:
        from refresh_guard import entry_time
    latest = state.get("latest_close")
    if not latest:
        return {"logged": 0, "skipped": "no latest close"}
    rows = calls.read(root, LOG)
    path = Path(root) / LOG
    previous = rows[-1]["hash"] if rows else ""
    missed = _append_missed(path, rows, previous, latest, now, entry_time)  # earlier closes nobody logged
    if missed:
        rows = calls.read(root, LOG)
        previous = rows[-1]["hash"]
    deadline = entry_time(pd.Timestamp(latest))
    if now >= deadline:
        return {"logged": 0, "missed": missed, "skipped": f"too late: the {latest} stance's entry ({deadline:%Y-%m-%d %H:%M} ET) has passed"}
    records, reason = records_for(state)
    if reason:
        return {"logged": 0, "missed": missed, "skipped": reason}
    done = {(r["latest_close"], r["instrument"]) for r in rows}
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
    return {"logged": logged, "missed": missed, "skipped": None if logged else f"the {latest} stance was already logged"}


def _append_missed(path: Path, rows: list[dict], previous: str, latest: str, now: pd.Timestamp, entry_time) -> int:
    """Review B6: a close between the log's first record and `latest` with no stance recorded before its next open
    gets a "missed" record, written now and labelled so (it is a new fact, not a backfilled stance)."""
    if not rows:
        return 0
    from validation import equity_sessions
    have = {(r["latest_close"], r["instrument"]) for r in rows}
    first = min(r["latest_close"] for r in rows)
    added = 0
    for day in equity_sessions(pd.Timestamp(first), pd.Timestamp(latest) - pd.Timedelta(days=1)):
        close = f"{day:%Y-%m-%d}"
        if now < entry_time(day):
            continue  # its entry is still ahead: not missed yet
        for symbol in SYMBOLS:
            if (close, symbol) in have:
                continue
            body = {"schema": 1, "id": len(rows) + added + 1, "source": "page",
                    "recorded_utc": now.tz_convert("UTC").isoformat(timespec="seconds"),
                    "recorded_et": now.tz_convert(NY).isoformat(timespec="seconds"), "latest_close": close,
                    "instrument": symbol, "direction": "missed", "rules": [], "close_only_rules": [],
                    "forward_below_rules": [], "opportunities": [], "rule_exits": {}, "recorded_after_entry": True,
                    "stance_rules": eligibility.RULES_VERSION, "horizon_sessions": HORIZON,
                    "headline": "Missed: no stance was recorded before this close's next open (laptop off or refresh failed)",
                    "evidence_sha256": None, "previous_hash": previous}
            row = {**body, "hash": calls._digest(body)}
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8", newline="\n") as stream:
                stream.write(json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n")
            previous, added = row["hash"], added + 1
    return added


def rule_exit(row: dict, etfs: dict, signals: list[dict] | None) -> dict | None:
    """A long record scored to its rule's own exit (2026-11-18, besides the fixed 5 sessions): each of its rules
    and exits as one paper trade from the next open, the same simulation as the paper book but per record, so
    overlapping records are each scored. None for a flat record."""
    if row.get("direction") != "long" or not row.get("rules"):
        return None
    from . import paper_book
    legs = [t for t in paper_book.trades([row], etfs, signals or []) if t.get("status") != "no_data"]
    closed = [t for t in legs if t["status"] == "closed"]
    return {"legs": [{k: t.get(k) for k in ("rule", "exit", "status", "net", "exit_date", "sessions")} for t in legs],
            "status": "closed" if legs and len(closed) == len(legs) else "open" if legs else "no_data",
            "net": sum(t["net"] for t in closed) / len(closed) if closed and len(closed) == len(legs) else None}


def summary(root: Path, etfs: dict, signals: list[dict] | None = None) -> dict:
    check = calls.verify(root, LOG)
    if not check["ok"]:
        return {"status": "broken", "reason": check["reason"], "records": [], "scoreboard": calls.scoreboard([])}
    rows = calls.read(root, LOG)
    scored, missed = [], sorted({r["latest_close"] for r in rows if r.get("direction") == "missed"})
    for row in rows:
        if row.get("direction") == "missed":
            continue  # recorded as missed (B6): nothing to score
        result = calls.score(row, etfs.get(row["instrument"]))
        scored.append({**result, "latest_close": row["latest_close"], "rules": row.get("rules", []),
                       "close_only_rules": row.get("close_only_rules", []),
                       "forward_below_rules": row.get("forward_below_rules", []), "stance_rules": row.get("stance_rules", 1),
                       "opportunities": opportunity.of_record(row), "rule_exit": rule_exit(row, etfs, signals)})
    by_symbol = {s: calls.scoreboard([x for x in scored if x["instrument"] == s]) for s in SYMBOLS}
    longs = [x for x in scored if x["direction"] == "long" and x.get("status") == "scored"]
    board = calls.scoreboard(scored)
    board["note"] = ("One record per ETF per close, each scored over the next 5 sessions from the next open, so "
                     "neighbouring days overlap and are not independent. Flat scores 0. Before costs, unlevered.")
    exits = [x["rule_exit"]["net"] for x in scored if x.get("rule_exit") and x["rule_exit"]["net"] is not None]
    return {"status": "ok", "horizon_sessions": HORIZON, "first_close": rows[0]["latest_close"] if rows else None,
            "missed_closes": missed,
            "scoreboard": board, "by_symbol": by_symbol, "long_scored": len(longs),
            "long_mean": sum(x["call_return"] for x in longs) / len(longs) if longs else None,
            "rule_exit_scored": len(exits), "rule_exit_mean": sum(exits) / len(exits) if exits else None,
            "rule_exit_note": "Long records also scored to their rule's own exit, bought at the next open, after the "
                              "backtester's 2 bp round trip; each record separately, so overlapping ones share days.",
            "records": list(reversed(scored))[:20]}
