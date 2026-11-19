"""Review: the research app's front page (review.html), combining this app with the backtester's files.

Approved 2026-11-19 (user, relayed by the backtester chat: "Yes, send both"). It is a summary, not a new log: it
reads the Daily thesis build (the same `state` that becomes thesis.html, one click away) plus the backtester's
optional files (exports/trade_simulation.json, exports/filter_tests.json), and works without them. Every callout
is marked act, watch or info and names its source.

Sections: Today (setups that fired or are close, the plan if one fired, risk), Levels for your charts, What
changed, Your record, Research queue.

Two decisions are the user's and not made yet, so nothing here assumes them: a maximum loss per trade (the plan
says "set a loss limit" until there is one in terminal_config.json's risk settings), and whether QQQ trades add
to a held position or stand alone.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from . import eligibility, signals

EVIDENCE = ("SPY", "QQQ")  # the ETFs whose rules have backtested evidence
LEVELS = ("SPY", "QQQ", "IWM")
FORWARD_NEEDED = 5  # forward trades before the backtester checks a Lead against its band (Lead v3)
EXIT_TEXT = {"hold_5": "sell at the close 5 sessions after the signal",
             "close_above_sma5": "sell at the first close above the 5-day average (at most 10 sessions)"}


def _callout(level: str, text: str, source: str) -> dict:
    return {"level": level, "text": text, "source": source}


def _optional_json(path: Path) -> tuple[dict | None, str | None]:
    """A backtester file, or None and why not (never an error: this app does not depend on the backtester)."""
    try:
        return json.loads(Path(path).read_text(encoding="utf-8")), None
    except FileNotFoundError:
        return None, "not found"
    except (OSError, ValueError) as exc:
        return None, f"unreadable ({str(exc)[:80]})"


def _loss_limit(root: Path) -> float | None:
    try:
        from terminal_config import load_config
        return (load_config(root).get("risk") or {}).get("max_loss_per_trade")
    except (ValueError, OSError):
        return None


def _sessions_ahead(latest: str | None, count: int) -> str | None:
    if not latest:
        return None
    return f"{pd.bdate_range(pd.Timestamp(latest) + pd.Timedelta(days=1), periods=count)[-1]:%Y-%m-%d}"


def today(state: dict, root: Path) -> dict:
    latest, stance = state.get("latest_close"), state.get("stance") or {}
    sigs = [s for s in state.get("signals") or [] if s.get("symbol") in EVIDENCE]
    callouts, setups = [], []
    for s in sigs:
        leads = eligibility.open_leads(s)
        near = bool(s.get("near_trigger"))
        if not (s.get("fired") or near):
            continue
        verdicts = sorted({e.get("verdict") for e in s.get("evidence") or [] if e.get("mode") == eligibility.ENTRY_MODE})
        setups.append({"symbol": s["symbol"], "rule": s["label"], "signal": s["signal"], "fired": bool(s.get("fired")),
                       "close": s.get("close"), "trigger_close": s.get("trigger_close"),
                       "distance": s["trigger_close"] / s["close"] - 1 if s.get("trigger_close") and s.get("close") else None,
                       "next_open_lead": bool(leads), "next_open_verdicts": verdicts})
        name = f"{s['symbol']} {s['label']}"
        if s.get("fired") and leads:
            callouts.append(_callout("act", f"{name} fired at the {latest} close, and buying at the next open is a "
                                     "backtested Lead. The plan is below.", "Daily thesis: registered signals"))
        elif s.get("fired"):
            callouts.append(_callout("info", f"{name} fired at the {latest} close, but buying at the next open is not "
                                     f"a Lead ({', '.join(verdicts) or 'untested'}), so it is not a setup now.",
                                     "Daily thesis: registered signals"))
        elif near and leads:
            callouts.append(_callout("watch", f"{name} fires if {s['symbol']} closes at or below "
                                     f"${s['trigger_close']:.2f} ({s['trigger_close'] / s['close'] - 1:+.1%} from "
                                     f"${s['close']:.2f}). It is a next-open Lead.", "Daily thesis: registered signals"))
    plan = []
    if stance.get("direction") == "long":
        limit = _loss_limit(root)
        for basis in stance.get("basis") or []:
            exit_name = next((k for k, v in signals.EXIT_LABELS.items() if v == basis.get("exit")), None)
            sig = next((s for s in sigs if s["symbol"] == basis["symbol"] and s["label"] == basis["rule"]), {})
            level = (f"about ${sig['sma5']:.2f} today (the 5-day average moves every day)"
                     if exit_name == "close_above_sma5" and sig.get("sma5") else
                     f"the close on {_sessions_ahead(latest, 5)}" if exit_name == "hold_5" else None)
            plan.append({"symbol": basis["symbol"], "rule": basis["rule"], "entry": f"the next open after the {latest} close",
                         "exit_rule": EXIT_TEXT.get(exit_name, basis.get("exit")), "exit_level": level,
                         "loss_at_limit": "set a loss limit" if not limit else f"{limit} (from your risk settings)",
                         "evidence": {k: basis.get(k) for k in ("dev_trades", "dev_mean_net", "dev_win_rate", "dev_excess")}})
        if plan and not _loss_limit(root):
            callouts.append(_callout("act", "Set a loss limit before acting on the plan: none is set, so no loss at "
                                     "your limit can be shown.", "terminal_config.json risk settings"))
    callouts += risk_callouts(state)
    return {"latest_close": latest, "stance": {k: stance.get(k) for k in ("direction", "headline", "status")},
            "setups": setups, "plan": plan, "callouts": callouts}


def risk_callouts(state: dict) -> list[dict]:
    out, latest = [], state.get("latest_close")
    end = _sessions_ahead(latest, 5)
    reg = state.get("regime") or {}
    events = [e for e in (reg.get("events") or {}).get("upcoming") or [] if latest and end and latest < e.get("date", "") <= end]
    for e in events:
        out.append(_callout("watch", f"{e['label']} on {e['date']}, inside the next 5 sessions.", "Daily thesis: events"))
    earn = [r for r in (state.get("earnings") or {}).get("rows") or [] if latest and end and latest < (r.get("next_date") or "") <= end]
    if earn:
        out.append(_callout("watch", "Mega-cap earnings in the next 5 sessions: "
                            + ", ".join(f"{r['name']} {r['next_date']}" for r in earn) + ".", "Daily thesis: earnings"))
    vol = reg.get("volatility") or {}
    if vol.get("vix") is not None:
        inverted = (vol.get("term_ratio") or 0) > 1
        level = "watch" if vol["vix"] >= 25 or inverted else "info"
        out.append(_callout(level, f"VIX {vol['vix']:.1f} ({vol.get('level', '')})"
                            + (f"; VIX above its 3-month version ({vol['term_ratio']:.2f}), a stress reading" if inverted else "")
                            + ".", "Cboe VIX and VIX3M"))
    if state.get("next_entry_et") and latest:
        gap = (pd.Timestamp(state["next_entry_et"]).tz_localize(None).normalize() - pd.Timestamp(latest)).days
        if gap >= 2:  # 1 is an ordinary weeknight
            out.append(_callout("watch", f"A weekend or holiday comes before the next open "
                                f"({pd.Timestamp(state['next_entry_et']):%a %b %d}): the reopening gap is larger.",
                                "Exchange calendar"))
    return out


def levels(state: dict) -> list[dict]:
    trend = ((state.get("regime") or {}).get("trend")) or {}
    out = []
    for symbol in LEVELS:
        mine = [s for s in state.get("signals") or [] if s.get("symbol") == symbol]
        if not mine and symbol not in trend:
            continue
        t = trend.get(symbol) or {}
        boll = next((s for s in mine if s.get("signal") == "bollinger_lower_close"), {})
        out.append({"symbol": symbol, "close": t.get("close") or (mine[0].get("close") if mine else None),
                    "triggers": [{"rule": s["label"], "close_at_or_below": s.get("trigger_close")} for s in mine],
                    "lower_band": boll.get("value"), "sma5": mine[0].get("sma5") if mine else None,
                    "sma50": t.get("sma50"), "sma200": t.get("sma200")})
    return out


def changes(state: dict, root: Path, export_dir: Path | None = None) -> dict:
    export_dir = Path(export_dir or signals.export_path().parent)
    callouts = []
    sim, why = _optional_json(export_dir / "trade_simulation.json")
    verdicts = (sim or {}).get("verdict_changes") or []
    if sim is None:
        callouts.append(_callout("info", f"The backtester's trade simulation is {why}; verdict changes can't be shown.",
                                 "backtester exports/trade_simulation.json"))
    for v in verdicts:
        callouts.append(_callout("watch", f"Verdict changed: {json.dumps(v)[:200]}", "backtester trade_simulation.json verdict_changes"))
    forward = []
    for s in state.get("signals") or []:
        for e in s.get("evidence") or []:
            f = e.get("forward") or {}
            if e.get("mode") != eligibility.ENTRY_MODE or e.get("verdict") not in ("Lead", eligibility.FORWARD_BELOW):
                continue
            forward.append({"symbol": s["symbol"], "rule": s["label"], "exit": e.get("exit_label") or e.get("exit"),
                            "verdict": e.get("verdict"), "trades": f.get("trades"), "status": f.get("status"),
                            "since": f.get("since"), "mean_excess": f.get("mean_excess"), "band_lower": f.get("band_lower")})
            if e.get("verdict") == eligibility.FORWARD_BELOW:
                callouts.append(_callout("act", f"{s['symbol']} {s['label']} ({e.get('exit_label')}) fell below its band "
                                         "in the forward record and is no longer a Lead.", "backtester forward record"))
    filters, fwhy = _optional_json(export_dir / "filter_tests.json")
    tests = [{"test": t.get("test"), "strategy": t.get("strategy"), "group": t.get("group_label"), "label": t.get("label"),
              "diff": t.get("diff"), "ci90": t.get("ci90"), "trades_in_group": t.get("group")}
             for t in (filters or {}).get("tests") or []]
    by_label = {}
    for t in tests:
        by_label[t["label"]] = by_label.get(t["label"], 0) + 1
    notable = [t for t in tests if t["label"] and t["label"] != "Insufficient evidence"]
    if tests:  # one dated summary line: these are results of one run, not something that changes daily
        callouts.append(_callout("info", f"Filter tests from the {str((filters or {}).get('generated_at', ''))[:10]} run: "
                                 + ", ".join(f"{n} {label.lower()}" for label, n in sorted(by_label.items(), key=lambda kv: -kv[1]))
                                 + ". The notable ones are listed below.", "backtester exports/filter_tests.json"))
    problems = [r for r in (state.get("ops") or {}).get("rows") or [] if r.get("state") != "ok"]
    for r in problems:
        callouts.append(_callout("watch" if r.get("state") == "late" else "act", f"{r['label']}: {r.get('detail')}",
                                 "Daily thesis: System status"))
    check = state.get("evidence_check") or {}
    age = check.get("age_days")
    if age is not None:
        callouts.append(_callout("watch" if age > eligibility.WARN_AFTER_DAYS else "info",
                                 f"The backtested evidence covers data through {check.get('checked_through')} "
                                 f"({age} day{'s' if age != 1 else ''} before the latest close).",
                                 "backtester export, checked by the thesis"))
    return {"callouts": callouts, "verdict_changes": verdicts, "forward": forward,
            "filter_tests": {"status": "ok" if filters else fwhy, "generated_at": (filters or {}).get("generated_at"),
                             "by_label": by_label, "notable": notable, "count": len(tests)},
            "problems": [{k: r.get(k) for k in ("label", "state", "last", "detail")} for r in problems]}


def record(state: dict) -> dict:
    book = state.get("paper_book") or {}
    open_trades = [t for t in book.get("trades") or [] if t.get("status") in ("open", "pending")]
    calls = (state.get("calls") or {}).get("calls") or []
    against = {}
    for c in calls:
        relation = c.get("relation") or "before links (2026-11-18)"
        bucket = against.setdefault(relation, {"calls": 0, "scored": 0, "returns": []})
        bucket["calls"] += 1
        if c.get("status") == "scored" and c.get("call_return") is not None:
            bucket["scored"] += 1
            bucket["returns"].append(c["call_return"])
    for b in against.values():
        b["mean_return"] = sum(b["returns"]) / len(b["returns"]) if b["returns"] else None
        del b["returns"]
    missed_closes = (state.get("stance_log") or {}).get("missed_closes") or []
    missed_decisions = (state.get("ops") or {}).get("missed_decisions") or []
    callouts = [_callout("act" if line.get("action") in ("enter", "exit") else "watch", line.get("text", ""),
                         "Daily thesis: paper ticket") for line in book.get("ticket") or []]
    if missed_closes:
        callouts.append(_callout("info", f"{len(missed_closes)} close(s) had no stance recorded before the next open: "
                                 + ", ".join(missed_closes[-6:]) + ". Leave the laptop asleep or on, not shut down.",
                                 "stance log (missed records)"))
    return {"open_trades": open_trades, "calls_by_relation": against, "calls": len(calls),
            "missed_closes": missed_closes, "missed_decisions": missed_decisions, "callouts": callouts}


def queue(state: dict) -> dict:
    ideas = (state.get("ideas") or {}).get("ideas") or []
    by_stage = {}
    for i in ideas:
        by_stage.setdefault(i.get("stage"), []).append({"idea": i.get("idea"), "title": i.get("title"),
                                                        "missing": i.get("missing") or [], "updated": i.get("updated")})
    due = []
    for s in state.get("signals") or []:
        for e in s.get("evidence") or []:
            if e.get("mode") != eligibility.ENTRY_MODE or e.get("verdict") != "Lead":
                continue
            have = (e.get("forward") or {}).get("trades") or 0
            card = next((c for c in s.get("cards") or [] if c.get("exit") == e.get("exit")), {})
            per_year = card.get("trades_per_year")
            months = round((FORWARD_NEEDED - have) / per_year * 12) if per_year and have < FORWARD_NEEDED else None
            due.append({"symbol": s["symbol"], "rule": s["label"], "exit": e.get("exit_label") or e.get("exit"),
                        "forward_trades": have, "needed": FORWARD_NEEDED, "trades_per_year": per_year,
                        "months_to_check": months})
    callouts = [_callout("info", f"{d['symbol']} {d['rule']} ({d['exit']}): {d['forward_trades']} of {d['needed']} forward "
                         "trades so far; at about " + (f"{d['trades_per_year']:.1f} a year that is roughly {d['months_to_check']} "
                                                       "months away." if d["months_to_check"] is not None else "an unknown rate."),
                         "backtester forward record and evidence cards") for d in due]
    return {"by_stage": by_stage, "counts": (state.get("ideas") or {}).get("counts") or {}, "forward_checks": due,
            "callouts": callouts}


def build(state: dict, root: Path, export_dir: Path | None = None) -> dict:
    sections = {"today": today(state, root), "levels": levels(state), "changes": changes(state, root, export_dir),
                "record": record(state), "queue": queue(state)}
    order = {"act": 0, "watch": 1, "info": 2}
    top = sorted([c for key in ("today", "changes", "record") for c in sections[key]["callouts"]],
                 key=lambda c: order.get(c["level"], 3))
    return {"as_of": state.get("as_of"), "latest_close": state.get("latest_close"), "headline": top[:12], **sections,
            "undecided": ["A maximum loss per trade (the plan shows \"set a loss limit\" until you set one).",
                          "Whether QQQ trades are add-ons to a held position or standalone."]}
