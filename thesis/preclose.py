"""Pre-close check: at about 3:50 PM ET, which registered rules would fire if today closed at the current price?

Why: in the backtest, buying at the signal close beat buying at the next open for every rule, and for SPY
RSI(2) < 10 the closing-price entry is the only Lead. The Daily thesis is built after the close, when that entry
has passed. This check is taken before the close (a market-on-close order must be in by about 3:50 PM ET), so
the closing-price evidence can be used and, more importantly, logged before the fact.

One record per session in data/thesis/preclose.jsonl (append-only, hash-chained; never edit by hand). Later
reads add what actually happened: whether each rule was still fired at the real close (the flip rate), and a
paper trade from that close to the rule's registered exit for rules whose closing-price pricing is a Lead.
The price is Yahoo's last trade when the check ran; it can be delayed and is not an executable quote.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from . import calls, data, eligibility, paper_book, signals
from .data import NY

LOG = Path("data/thesis/preclose.jsonl")
SYMBOLS = ("SPY", "QQQ", "IWM")
WINDOW = (15 * 60 + 30, 16 * 60)  # minutes after midnight ET in which a check may be recorded


def evaluate(etfs: dict, prices: dict, day: pd.Timestamp, payload: dict | None) -> list[dict]:
    """Each rule's state if `day` closed at prices[symbol]. etfs must end before `day`."""
    rows = []
    built = {(s["symbol"], s["signal"]): s for s in signals.build(etfs, payload)["signals"]}
    for symbol in SYMBOLS:
        frame, price = etfs.get(symbol), prices.get(symbol)
        if frame is None or len(frame) < 60 or not price or frame.index[-1] >= day:
            continue
        close = pd.concat([frame["close"], pd.Series([float(price)], index=[day])])
        for name, (label, rule, _) in signals.RULES.items():
            sig = built.get((symbol, name)) or {}
            trigger = sig.get("trigger_close")
            close_leads = sorted({e["exit"] for e in sig.get("evidence") or []
                                  if e.get("verdict") == "Lead" and e.get("mode") == "etf_close"})
            rows.append({"symbol": symbol, "signal": name, "label": label, "price": float(price), "trigger": trigger,
                         "distance": float(price) / trigger - 1 if trigger else None,
                         "fired": bool(rule(close).iloc[-1]), "close_lead_exits": close_leads,
                         "next_open_lead": bool(eligibility.open_leads(sig))})
    return rows


def record(root: Path, now: pd.Timestamp, quote_for, force: bool = False) -> dict:
    """Append today's check (once per session, only 3:30-4:00 PM ET on a trading day unless forced in a test)."""
    from validation import equity_sessions
    local = now.tz_convert(NY)
    day = local.tz_localize(None).normalize()
    minutes = local.hour * 60 + local.minute
    if not force and (len(equity_sessions(day, day)) != 1 or not WINDOW[0] <= minutes < WINDOW[1]):
        return {"recorded": False, "skipped": "outside 3:30-4:00 PM ET on a trading day"}
    rows = calls.read(root, LOG)
    session = f"{day:%Y-%m-%d}"
    if any(r["session"] == session for r in rows):
        return {"recorded": False, "skipped": "already recorded for this session"}
    etfs = data.etfs(root, now)
    prior = equity_sessions(day - pd.Timedelta(days=14), day - pd.Timedelta(days=1))
    newest = max((f.index[-1] for s, f in etfs.items() if s in SYMBOLS), default=None)
    if not force and (newest is None or (len(prior) and newest < prior[-1])):
        # a rule's value depends on every prior close; a missing day would log a wrong check for good
        return {"recorded": False, "skipped": f"saved daily history ends {newest:%Y-%m-%d}; yesterday's refresh is missing"
                if newest is not None else "no saved daily history"}
    payload, info = signals.load_export()
    prices, problems = {}, []
    for symbol in SYMBOLS:
        try:
            price = (quote_for(symbol) or {}).get("price")
            if not price or float(price) <= 0:
                raise ValueError("no price")
            prices[symbol] = float(price)
        except Exception as exc:
            problems.append(f"{symbol}: {exc}")
    checks = evaluate(etfs, prices, day, payload)
    if not checks:
        return {"recorded": False, "skipped": "no price or history: " + "; ".join(problems)}
    utc = now.tz_convert("UTC")
    body = {"schema": 1, "id": len(rows) + 1, "session": session, "recorded_utc": utc.isoformat(timespec="seconds"),
            "recorded_et": local.isoformat(timespec="seconds"), "source": "Yahoo last trade (may be delayed)",
            "history_through": f"{max(f.index[-1] for f in etfs.values()):%Y-%m-%d}" if etfs else None,
            "evidence_sha256": info.get("sha256"), "evidence_status": info.get("status"), "checks": checks,
            "problems": problems, "previous_hash": rows[-1]["hash"] if rows else ""}
    row = {**body, "hash": calls._digest(body)}
    path = Path(root) / LOG
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n")
    fired = [f"{c['symbol']} {c['signal']}" for c in checks if c["fired"]]
    return {"recorded": True, "session": session, "fired": fired, "problems": problems}


def summary(root: Path, etfs: dict, payload_signals: list[dict] | None = None) -> dict:
    check = calls.verify(root, LOG)
    if not check["ok"]:
        return {"status": "broken", "reason": check["reason"], "sessions": []}
    sessions, held, flipped, close_records = [], 0, 0, []
    for row in calls.read(root, LOG):
        day = pd.Timestamp(row["session"])
        out = []
        for c in row["checks"]:
            frame = etfs.get(c["symbol"])
            actual = None
            if frame is not None and day in frame.index:
                rule = signals.RULES[c["signal"]][1]
                actual = bool(rule(frame["close"][frame.index <= day]).iloc[-1])
                held, flipped = held + (actual == c["fired"]), flipped + (actual != c["fired"])
                if c["fired"] and c.get("close_lead_exits"):
                    close_records.append({"latest_close": row["session"], "instrument": c["symbol"], "rules": [c["signal"]],
                                          "rule_exits": {c["signal"]: c["close_lead_exits"]}, "confirmed": actual})
            out.append({**c, "fired_at_close": actual,
                        "close": float(frame["close"].loc[day]) if frame is not None and day in frame.index else None})
        sessions.append({"session": row["session"], "recorded_et": row["recorded_et"], "source": row.get("source"),
                         "checks": out, "problems": row.get("problems") or []})
    trades = paper_book.trades(close_records, etfs, payload_signals or [], entry="close")
    return {"status": "ok", "count": len(sessions), "sessions": list(reversed(sessions))[:10],
            "compared": held + flipped, "held": held, "flipped": flipped,
            "trades": list(reversed(trades)), "scoreboard": paper_book.scoreboard(trades),
            "note": "Each rule is checked against the price at about 3:50 PM ET, then against the real close. "
                    "Paper trades here are bought at that day's close, for rules whose closing-price entry is a "
                    "backtested Lead, including the days when the rule was no longer fired at the close."}
