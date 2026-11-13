"""Paper book: the registered rules' own paper trades, followed from entry to their registered exit.

Nothing here is a new log. It is a view computed from records that were written before the fact:
- the page's stance log (thesis/stance_log.py): every "long" record opens one paper trade per rule and exit, bought
  at the next session's open, exactly as the backtester prices "buy at the next open";
- the pre-close log (thesis/preclose.py) passes entry="close" for rules seen fired at 3:50 PM ET.
Exits are the backtester's (backtester/strategies.py): "hold_5" sells at the close five sessions after the signal;
"close_above_sma5" sells at the first close above the 5-day average, at most ten sessions after the signal.
One position at a time per ETF, rule and exit: a signal that arrives while one is open is skipped, as in the
backtest. Costs: the backtester's 2 bp round trip. Unlevered, no stops. It never places an order; the "ticket" is
what these paper trades do next, for the user to act on or not.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from . import eligibility

COST = 0.0002
EXIT_TEXT = {"hold_5": "hold 5 sessions", "close_above_sma5": "first close above the 5-day average (max 10 sessions)"}
MAX_SESSIONS = {"hold_5": 5, "close_above_sma5": 10}


def _day(ts) -> str:
    return f"{pd.Timestamp(ts):%Y-%m-%d}"


def simulate(frame: pd.DataFrame | None, signal_day: str, exit_name: str, entry: str = "next_open") -> dict:
    """One paper trade from its signal day. Status: no_data, pending (entry not in the data yet), open or closed."""
    if frame is None or frame.empty or exit_name not in MAX_SESSIONS:
        return {"status": "no_data"}
    pos = int(frame.index.get_indexer([pd.Timestamp(signal_day)])[0])
    if pos < 0:
        return {"status": "no_data"}
    close, open_ = frame["close"].to_numpy(float), frame["open"].to_numpy(float)
    last = len(frame) - 1
    entry_pos = pos + 1 if entry == "next_open" else pos
    if entry_pos > last:
        return {"status": "pending", "signal_day": signal_day}
    entry_price = float(open_[entry_pos] if entry == "next_open" else close[pos])
    limit = pos + MAX_SESSIONS[exit_name]
    exit_pos = None
    if exit_name == "hold_5":
        exit_pos = limit if limit <= last else None
    else:
        above = close > pd.Series(close).rolling(5, min_periods=5).mean().to_numpy()
        hits = [d for d in range(pos + 1, min(limit, last) + 1) if above[d]]
        exit_pos = hits[0] if hits else (limit if limit <= last else None)
    out = {"signal_day": signal_day, "entry_date": _day(frame.index[entry_pos]), "entry_price": entry_price}
    if exit_pos is not None:
        gross = float(close[exit_pos] / entry_price - 1)
        return {**out, "status": "closed", "exit_date": _day(frame.index[exit_pos]), "exit_price": float(close[exit_pos]),
                "sessions": exit_pos - pos, "gross": gross, "net": gross - COST,
                "exit_reason": "time limit" if exit_pos == limit and exit_name != "hold_5" and not above[exit_pos]
                else "registered exit"}
    held = last - pos
    out.update(status="open", through=_day(frame.index[last]), last_close=float(close[last]), sessions=held,
               sessions_left=limit - last, gross=float(close[last] / entry_price - 1))
    if exit_name == "close_above_sma5" and last >= 3:
        # tomorrow's close c exits when c > mean(last four closes, c), i.e. c > mean of the last four closes
        out["exit_above"] = float(np.mean(close[last - 3:last + 1]))
    return out


def _evidence_exits(signals: list[dict], symbol: str, rule: str, mode: str) -> dict[str, dict]:
    """exit name -> the backtester's evidence row, for Lead pricings of this rule and entry mode."""
    for s in signals or []:
        if s.get("symbol") == symbol and s.get("signal") == rule:
            return {e["exit"]: e for e in s.get("evidence") or [] if e.get("verdict") == "Lead" and e.get("mode") == mode}
    return {}


def trades(records: list[dict], etfs: dict, signals: list[dict], entry: str = "next_open") -> list[dict]:
    """Paper trades for long records (each: latest_close, instrument, rules, optional rule_exits)."""
    mode = eligibility.ENTRY_MODE if entry == "next_open" else "etf_close"
    out, busy = [], {}
    for record in sorted(records, key=lambda r: (r["latest_close"], r["instrument"])):
        symbol, frame = record["instrument"], etfs.get(record["instrument"])
        for rule in record.get("rules") or []:
            evidence = _evidence_exits(signals, symbol, rule, mode)
            exits = (record.get("rule_exits") or {}).get(rule) or sorted(evidence)
            for exit_name in exits:
                key = (symbol, rule, exit_name)
                dev = (evidence.get(exit_name) or {}).get("development") or {}
                base = {"instrument": symbol, "rule": rule, "exit": exit_name, "exit_text": EXIT_TEXT.get(exit_name, exit_name),
                        "entry_mode": entry, "backtest_mean_net": dev.get("mean_net"), "backtest_win_rate": dev.get("win_rate"),
                        "backtest_trades": dev.get("trades"), "exit_from_current_evidence": "rule_exits" not in record}
                if key in busy and record["latest_close"] <= busy[key]:
                    out.append({**base, "status": "overlap_skipped", "signal_day": record["latest_close"]})
                    continue
                trade = simulate(frame, record["latest_close"], exit_name, entry)
                if trade["status"] == "closed":
                    busy[key] = trade["exit_date"]
                elif trade["status"] in ("open", "pending"):
                    busy[key] = "9999-12-31"
                out.append({**base, **trade})
    return out


def scoreboard(rows: list[dict]) -> dict:
    closed = [r for r in rows if r["status"] == "closed"]
    expected = [r["backtest_mean_net"] for r in closed if r.get("backtest_mean_net") is not None]
    mean = lambda xs: sum(xs) / len(xs) if xs else None  # noqa: E731
    return {"trades": len([r for r in rows if r["status"] in ("open", "closed", "pending")]), "closed": len(closed),
            "open": sum(r["status"] == "open" for r in rows), "pending": sum(r["status"] == "pending" for r in rows),
            "skipped": sum(r["status"] == "overlap_skipped" for r in rows),
            "win_rate": mean([1.0 if r["net"] > 0 else 0.0 for r in closed]), "mean_net": mean([r["net"] for r in closed]),
            "backtest_mean_net": mean(expected),
            "note": "After the backtester's 2 bp round trip, unlevered. The backtest figure is the average of these "
                    "same rules' 2010-on results. A handful of trades cannot confirm or reject it."}


def ticket(rows: list[dict]) -> list[dict]:
    """What the open and pending paper trades do at the next session."""
    lines = []
    for r in rows:
        name = f"{r['instrument']} · {r['rule']} ({r['exit_text']})"
        if r["status"] == "pending":
            when = "at the next open" if r["entry_mode"] == "next_open" else "at the signal close"
            lines.append({"action": "enter", "instrument": r["instrument"], "text": f"Enter: paper long {name}, bought {when}."})
        elif r["status"] == "open":
            if r["sessions_left"] <= 1:
                text = f"Exit: {name} sells at the next close (last session of its limit)."
            elif r.get("exit_above") is not None:
                text = (f"Watch: {name} sells at the next close if {r['instrument']} closes above ${r['exit_above']:.2f}; "
                        f"otherwise it holds ({r['sessions_left']} sessions left).")
            else:
                text = f"Hold: {name}, {r['sessions_left']} sessions left."
            lines.append({"action": "exit" if r["sessions_left"] <= 1 else "watch", "instrument": r["instrument"], "text": text})
    return lines


def legacy_open(root: Path, now: pd.Timestamp) -> list[dict]:
    """Open paper trades of the frozen four-rule experiment (read from its log; shown for completeness)."""
    path = Path(root) / "data" / "monitor" / "paper_events.jsonl"
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if e.get("type") == "decision" and e.get("signal") and e.get("exit_at") and pd.Timestamp(e["exit_at"]) > now:
            out.append({"name": e.get("name"), "side": "long" if e.get("side", 0) > 0 else "short",
                        "entry_at": e.get("entry_at"), "exit_at": e.get("exit_at"), "state": e.get("state")})
    return out


def build(root: Path, now: pd.Timestamp, etfs: dict, signals: list[dict], stance_rows: list[dict]) -> dict:
    longs = [r for r in stance_rows if r.get("direction") == "long" and r.get("rules")]
    rows = trades(longs, etfs, signals)
    return {"status": "ok", "trades": list(reversed(rows)), "scoreboard": scoreboard(rows), "ticket": ticket(rows),
            "legacy_open": legacy_open(root, now),
            "note": "These are the registered rules' paper trades, entered at the next open after each logged long "
                    "stance and held to the rule's own exit. They are research records, not orders and not advice."}
