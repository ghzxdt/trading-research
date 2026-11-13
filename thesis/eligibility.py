"""One shared answer to "can this be called long?", used by the page (build.stance) and the stance log.

Stance rules v2 (2026-11-13; v1 was fixed 2026-11-08):
- A fired rule counts only if the backtester rated its *next-open* pricing a Lead. The page is built after the
  close, so the closing-price entry has passed; a rule that is a Lead only at the close is shown as
  "fired, but not a setup now" and is logged flat.
- No stance at all (not flat, not long) when the evidence can't be used: the export is missing or unreadable,
  a symbol or rule has no evidence in it, a rule's fired dates no longer match the backtester, the definitions
  could not be checked, or the export is too old.
"""
from __future__ import annotations

import pandas as pd

ENTRY_MODE = "etf_next_open"  # the only entry still available when the page is read
RULES_VERSION = 2
WARN_AFTER_DAYS = 10   # show the evidence's age as a caution
MAX_AGE_DAYS = 45      # beyond this the evidence is not used at all
SYMBOLS = ("SPY", "QQQ")


def open_leads(signal: dict) -> list[dict]:
    """Evidence rows rated Lead for the entry that is still available (buy at the next open)."""
    return [e for e in signal.get("evidence") or [] if e.get("verdict") == "Lead" and e.get("mode") == ENTRY_MODE]


def close_only_leads(signal: dict) -> list[dict]:
    """Lead rows for an entry that has passed, when the next-open entry is not a Lead."""
    if open_leads(signal):
        return []
    return [e for e in signal.get("evidence") or [] if e.get("verdict") == "Lead"]


def evidence_check(source: dict | None, signals: list[dict], latest_close: str | None,
                   symbols: tuple[str, ...] = SYMBOLS) -> dict:
    """Whether the backtester's evidence can back a stance for `latest_close`, and why not if it can't."""
    out = {"usable": False, "status": "ok", "reason": None, "warning": None, "checked_through": None, "age_days": None}
    source = source or {}
    if source.get("status") != "ok":
        detail = source.get("reason")
        return {**out, "status": source.get("status") or "unavailable",
                "reason": "The backtester's evidence is unavailable" + (f": {detail}" if detail else ".")}
    rows = [s for s in signals or [] if s.get("symbol") in symbols]
    for symbol in symbols:
        mine = [s for s in rows if s["symbol"] == symbol]
        if not mine:
            return {**out, "status": "partial", "reason": f"There is no signal data for {symbol}."}
        empty = [s.get("signal", "?") for s in mine if not s.get("evidence")]
        if empty:
            return {**out, "status": "partial",
                    "reason": f"The backtester's export has no evidence for {symbol} ({', '.join(empty)})."}
    name = lambda s: f"{s['symbol']} {s.get('signal', '?')}"  # noqa: E731
    drift = [name(s) for s in rows if (s.get("crosscheck") or {}).get("status") == "mismatch"]
    if drift:
        return {**out, "status": "mismatch",
                "reason": "Rule definitions no longer match the backtester: " + ", ".join(drift) + "."}
    unchecked = [name(s) for s in rows if (s.get("crosscheck") or {}).get("status") != "match"]
    if unchecked:
        return {**out, "status": "unchecked",
                "reason": "The rule definitions could not be checked against the backtester: " + ", ".join(unchecked) + "."}
    through = [s["crosscheck"]["checked_through"] for s in rows if s["crosscheck"].get("checked_through")]
    if through and latest_close:
        oldest = min(through)
        age = int((pd.Timestamp(latest_close) - pd.Timestamp(oldest)).days)
        out.update(checked_through=oldest, age_days=age)
        if age > MAX_AGE_DAYS:
            return {**out, "status": "stale",
                    "reason": f"The backtester's evidence is {age} days old (it covers data through {oldest}). "
                              "Run 'Run trade simulation' in the Trading Backtester app."}
        if age > WARN_AFTER_DAYS:
            out["warning"] = (f"The backtested evidence is {age} days old (through {oldest}). It is still used; "
                              "re-run the trade simulation in the Trading Backtester app to refresh it.")
    return {**out, "usable": True}
