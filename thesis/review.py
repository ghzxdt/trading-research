"""Review: the research app's front page (review.html), combining this app with the backtester's files.

v1 approved 2026-11-19 (user, relayed by the backtester chat: "Yes, send both"). v2 follows the backtester chat's
spec docs/REVIEW_PAGE_V2_2026-11-21.md in that repo (user: "Yes, send it", 2026-11-21): profit, edges and the
information for a thesis, as one loop.

It is a read model, not a new log: it reads the Daily thesis build (the same `state` that becomes thesis.html, one
click away) plus the backtester's optional files (exports/trade_simulation.json, exports/evidence.json through the
signals' cards, exports/filter_tests.json and the trade list exports/trades/<run>.csv), and works without them.
Every callout is marked act, watch or info and names its source. The same inputs give the same page.

Rules it keeps (the spec's guardrails):
- tested evidence outranks information: each context item carries the tag its registered filter test gives it for
  the rule in play (tested edge, tested with no effect, unresolved, untested), and only a Lead triggers a plan;
- every number shows its n, and an interval where the backtester exports one; small samples say so;
- no composite score and no probability of profit; agreeing context is never added up;
- statistics come from the backtester's files. Only price levels (averages, ATR, swing points, trigger closes) and
  the open rule trades' own paths are computed here, from this app's daily data.

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
SMALL_SAMPLE = 30  # fewer trades than this: labelled a small sample
TOO_FEW = 20  # fewer scored items than this in a group: "too few to judge"
ANALOGS = 8  # the last few times a setup fired, from the trade list
SHORT = {"bollinger_lower_close": "Bollinger", "rsi14_below_30": "RSI(14)", "rsi2_below_10": "RSI(2)"}
TIME_STOP = {"hold_5": 5, "close_above_sma5": 10}  # sessions after the signal (the backtester's exits)
EXIT_TEXT = {"hold_5": "sell at the close 5 sessions after the signal",
             "close_above_sma5": "sell at the first close above the 5-day average (at most 10 sessions)"}
ENTRY = {"etf_close": "at the close", "etf_next_open": "at the next open"}
NY = "America/New_York"

# Context item -> its registered filter test (spec step 1.3). A newly registered filter test needs one row here
# plus, if it should be flagged as active today, a line in context_state().
CONTEXT = (
    {"id": "vix_level", "test": "vix_level", "label": "VIX 20 or higher"},
    {"id": "vix_term", "test": "vix_term_structure", "label": "VIX above VIX3M"},
    {"id": "spy_trend", "test": "spy_200d_trend", "label": "SPY below its 200-day average"},
    {"id": "release", "test": "release_within_5_sessions", "label": "A release within 5 sessions"},
    {"id": "gap", "test": "gap_at_next_open", "label": "A gap up of 0.5% or more at the next open"},
)
TAG_NAMES = {"edge": "tested edge", "no_effect": "tested, no effect", "unresolved": "unresolved",
             "untested": "untested", "difference": "tested, difference shown"}


def _callout(level: str, text: str, source: str, tags: list | None = None) -> dict:
    out = {"level": level, "text": text, "source": source}
    if tags:
        out["tags"] = tags
    return out


def _optional_json(path: Path) -> tuple[dict | None, str | None]:
    """A backtester file, or None and why not (never an error: this app does not depend on the backtester)."""
    try:
        return json.loads(Path(path).read_text(encoding="utf-8")), None
    except FileNotFoundError:
        return None, "not found"
    except (OSError, ValueError) as exc:
        return None, f"unreadable ({str(exc)[:80]})"


def _base(name: str | None) -> str:
    return str(name or "").split("@")[0]


def _day(value) -> str:
    t = pd.Timestamp(value)
    return f"{t:%a %b} {t.day}"


def _num(value, spec: str, missing: str = "unknown") -> str:
    return missing if value is None else format(value, spec)


# ---- sessions, holding window and catalysts --------------------------------------------------------------------

def sessions_after(day: str | None, count: int) -> list[str]:
    """The next `count` exchange sessions after `day` (NYSE holidays excluded; business days counted Thanksgiving)."""
    if not day or count < 1:
        return []
    from validation import equity_sessions
    start = pd.Timestamp(day)
    return [f"{d:%Y-%m-%d}" for d in equity_sessions(start + pd.Timedelta(days=1), start + pd.Timedelta(days=count * 2 + 14))][:count]


def _holiday_name(day: str) -> str:
    d = pd.Timestamp(day)
    if d.month == 11 and d.day_of_week == 3:
        return "Thanksgiving"
    if d.month == 12 and 24 <= d.day <= 26:
        return "Christmas"
    if d.month == 1 and d.day <= 2:
        return "New Year's Day"
    if d.month == 7 and 3 <= d.day <= 5:
        return "Independence Day"
    return "market holiday"


def holding_window(latest: str | None, sessions: int) -> dict | None:
    """From the session after the signal to the rule's time stop, with the weekdays the market is closed and the
    early closes inside it."""
    days = sessions_after(latest, sessions)
    if not days:
        return None
    from intraday.calendar import EARLY_CLOSES
    weekdays = [f"{d:%Y-%m-%d}" for d in pd.bdate_range(pd.Timestamp(latest) + pd.Timedelta(days=1), days[-1])]
    return {"from": days[0], "to": days[-1], "sessions": len(days),
            "closed": [d for d in weekdays if d not in set(days)], "early_closes": [d for d in days if d in EARLY_CLOSES]}


def catalysts(state: dict, latest: str | None, window: dict | None) -> list[dict]:
    """Releases, mega-cap earnings, holidays and half days from the signal to the window's last session."""
    if not latest or not window:
        return []
    end, out = window["to"], []
    for e in ((state.get("regime") or {}).get("events") or {}).get("upcoming") or []:
        if latest < str(e.get("date", "")) <= end:
            out.append({"date": e["date"], "kind": "release",
                        "what": e.get("label", "release") + (f" ({e['time_et']} ET)" if e.get("time_et") else "")})
    for r in (state.get("earnings") or {}).get("rows") or []:
        if latest < str(r.get("next_date") or "") <= end:
            out.append({"date": r["next_date"], "kind": "earnings", "what": f"{r.get('name')} earnings"})
    for d in window.get("closed") or []:
        out.append({"date": d, "kind": "holiday", "what": f"Market closed ({_holiday_name(d)})"})
    for d in window.get("early_closes") or []:
        out.append({"date": d, "kind": "half day", "what": "Half day: the market closes at 1 PM ET"})
    return sorted(out, key=lambda c: (c["date"], c["kind"]))


def _releases_within(state: dict, latest: str | None, sessions: int = 5) -> list[dict]:
    days = sessions_after(latest, sessions)
    if not days:
        return []
    return [e for e in ((state.get("regime") or {}).get("events") or {}).get("upcoming") or []
            if latest < str(e.get("date", "")) <= days[-1]]


# ---- filter-test tags ---------------------------------------------------------------------------------------------

def load_filters(export_dir: Path) -> tuple[dict | None, str | None]:
    return _optional_json(Path(export_dir) / "filter_tests.json")


def filter_test(filters: dict | None, symbol: str, signal: str, exit_name: str, mode: str, test: str) -> dict | None:
    key = f"{symbol}:{_base(signal)}+{_base(exit_name)}|{mode}"
    return next((t for t in (filters or {}).get("tests") or []
                 if t.get("test") == test and str(t.get("strategy", "")).replace("@v1", "") == key), None)


def tag(test: dict | None) -> dict:
    """The tag one registered filter test gives a context item for one rule (spec step 1.3)."""
    if not test:
        return {"tag": "untested", "text": "untested (no registered test for this rule)"}
    label, p, q, diff = test.get("label") or "", test.get("p"), test.get("q"), test.get("diff")
    hold = test.get("holdout") or {}
    disagrees = bool(hold.get("status") == "ok" and hold.get("diff") is not None and diff is not None
                     and (hold["diff"] > 0) != (diff > 0))
    numbers = {k: test.get(k) for k in ("group_label", "group", "rest", "diff", "ci90", "p", "q")}
    numbers["holdout_diff"], numbers["holdout_disagrees"] = hold.get("diff"), disagrees
    if label == "Too few trades" or p is None:
        return {"tag": "untested", "text": "untested (too few trades)", **numbers}
    if label == "No meaningful difference" or p >= 0.10:
        return {"tag": "no_effect", "text": "tested, no difference shown", **numbers}
    if q is None or q >= 0.10 or disagrees:
        return {"tag": "unresolved", "text": "unresolved", **numbers}
    return {"tag": "difference", "text": f"tested: {label.lower() or 'a difference'} (a filter becomes a rule only as a "
                                         "new strategy version)", **numbers}


def tags_for(test_id: str, rules: list[dict], filters: dict | None) -> list[dict]:
    return [{"rule": r["short"], "test": test_id,
             **tag(filter_test(filters, r["symbol"], r["signal"], r["exit"], r["mode"], test_id))} for r in rules]


def _who(names: list[str], total: int) -> str:
    if len(names) == total and total == 2:
        return "both rules"
    if len(names) == total and total > 2:
        return f"all {total} rules"
    return " and ".join(names)


def phrase(tags: list[dict]) -> str:
    """One sentence for a context item's tags across the rules in play (agreeing tags are not added up)."""
    if not tags:
        return "no rule in play to test it against"
    groups: dict[str, list[dict]] = {}
    for t in tags:
        groups.setdefault(t["text"], []).append(t)
    parts = []
    for text, items in groups.items():
        who = _who([t["rule"] for t in items], len(tags))
        if items[0]["tag"] == "no_effect":
            parts.append(f"tested on {who if len(tags) > 1 else 'this rule'}, no difference shown")
        elif items[0]["tag"] == "untested":
            parts.append(f"{text} for {who}")
        elif items[0]["tag"] == "unresolved":
            details = []
            for t in items:
                if t.get("diff") is None:
                    continue
                n = (t.get("group") or 0) + (t.get("rest") or 0)
                details.append(f"{t['rule']} trades did {abs(t['diff']):.1%} {'worse' if t['diff'] < 0 else 'better'} "
                               f"({t.get('group')} of {n} trades, p {_num(t.get('p'), '.2f')}, q {_num(t.get('q'), '.2f')})")
            tail = "; 1993-2009 did not show it" if all(t.get("holdout_disagrees") for t in items) else ""
            parts.append(f"unresolved for {who}" + (": since 2010, " + "; ".join(details) if details else "") + tail)
        else:
            parts.append(f"{text} for {who}")
    return "; ".join(parts)


def context_state(state: dict, latest: str | None) -> dict:
    """Whether each context item holds today (None: not known until later, e.g. the next open's gap)."""
    reg = state.get("regime") or {}
    vol, spy = reg.get("volatility") or {}, (reg.get("trend") or {}).get("SPY") or {}
    vix, ratio = vol.get("vix"), vol.get("term_ratio")
    releases = _releases_within(state, latest)
    return {"vix_level": {"active": None if vix is None else vix >= 20, "detail": None if vix is None else f"VIX {vix:.1f}"},
            "vix_term": {"active": None if ratio is None else ratio > 1,
                         "detail": None if ratio is None else f"VIX {vix:.1f} vs VIX3M {vol.get('vix3m') or 0:.1f}"},
            "spy_trend": {"active": None if spy.get("vs_sma200") is None else spy["vs_sma200"] < 0,
                          "detail": None if spy.get("vs_sma200") is None else f"SPY {spy['vs_sma200']:+.1%} from its 200-day average"},
            "release": {"active": bool(releases), "detail": "; ".join(f"{e.get('label')} {e.get('date')}" for e in releases) or None},
            "gap": {"active": None, "detail": "known at the next open"}}


# ---- the trade: spread, sizing, rule trades, analogs ---------------------------------------------------------------

def spread(card: dict | None) -> dict | None:
    """The evidence card's distribution, as the plan shows it (the backtester's numbers, not recomputed)."""
    if not card:
        return None
    lev = card.get("leveraged") or {}
    dev = card.get("development") or {}
    return {"trades": card.get("trades"), "since": str(dev.get("start") or "2010")[:4],
            "small": bool(card.get("trades") is not None and card["trades"] < SMALL_SAMPLE),
            "mean_net": card.get("mean_net"), "median_net": card.get("median_net"), "net_p10": card.get("net_p10"),
            "worst_trade": card.get("worst_trade"), "worst_inside": card.get("worst_inside"),
            "trades_mae_below_5pct": card.get("trades_mae_below_5pct"), "excess": card.get("excess"),
            "excess_ci90": card.get("excess_ci90"), "trades_per_year": card.get("trades_per_year"),
            "leveraged": {k: lev.get(k) for k in ("instrument", "trades", "worst_net", "mae_worst")} if lev else None}


def spread_text(short: str, mode: str, s: dict | None) -> str:
    if not s:
        return f"{short}, {ENTRY.get(mode, mode)}: no evidence card"
    text = (f"{short}, {ENTRY.get(mode, mode)}, {s['trades']} trades since {s['since']}"
            + (" (a small sample)" if s["small"] else "")
            + f": mean {_num(s['mean_net'], '+.2%')}, median {_num(s['median_net'], '+.2%')}, "
              f"10th percentile {_num(s['net_p10'], '+.2%')}, worst {_num(s['worst_trade'], '+.1%')}")
    if s.get("trades_mae_below_5pct") is not None:
        text += f"; {s['trades_mae_below_5pct']} went more than 5% against before exiting"
    if s.get("worst_inside") is not None:
        text += f"; worst point inside a trade {s['worst_inside']:+.1%}"
    lev = s.get("leveraged") or {}
    if lev.get("worst_net") is not None:
        text += f"; {lev.get('instrument')} version: worst {lev['worst_net']:+.1%}"
    return text


def loss_limit(root: Path) -> dict:
    """The user's loss limit per trade as a fraction of the account: risk.max_loss_per_trade below 1 is read as
    a fraction; a dollar amount is divided by risk.account_equity. Unset until the user sets it."""
    try:
        from terminal_config import load_config
        risk = load_config(root).get("risk") or {}
    except (ValueError, OSError):
        return {"fraction": None, "reason": "terminal_config.json could not be read"}
    value, equity = risk.get("max_loss_per_trade"), risk.get("account_equity")
    if value in (None, "") or not isinstance(value, (int, float)) or value <= 0:
        return {"fraction": None, "reason": "no loss limit is set"}
    if value < 1:
        return {"fraction": float(value), "reason": None}
    if isinstance(equity, (int, float)) and equity > 0:
        return {"fraction": float(value) / float(equity), "reason": None}
    return {"fraction": None, "reason": "a dollar loss limit needs risk.account_equity to become a % of the account"}


def sizing(limit: float | None, worst_inside: float | None = None, leveraged_worst: float | None = None,
           wrong_if_distance: float | None = None) -> dict:
    """Arithmetic on the user's own limit, as % of the account (spec step 2.7): the limit divided by the distance
    to the "wrong if" level, and beside it the size at which the rule's worst past drawdown inside a trade would
    cost the full limit, at 1x and in the leveraged ETF. Not an approved size: sizing stays the user's call."""
    if not limit:
        return {"status": "no_limit", "text": "set a loss limit"}
    out = {"status": "ok", "limit": limit,
           "at_wrong_if": limit / abs(wrong_if_distance) if wrong_if_distance else None,
           "at_worst_1x": limit / abs(worst_inside) if worst_inside else None,
           "at_worst_leveraged": limit / abs(leveraged_worst) if leveraged_worst else None}
    bits = []
    if out["at_wrong_if"] is not None:
        bits.append(f"{out['at_wrong_if']:.1%} of the account loses {limit:.2%} at your wrong-if level")
    else:
        bits.append("no wrong-if level yet (the rules have no stop; record one in your call)")
    if out["at_worst_1x"] is not None:
        bits.append(f"{out['at_worst_1x']:.1%} at 1x would lose {limit:.2%} at the rule's worst past drawdown")
    if out["at_worst_leveraged"] is not None:
        bits.append(f"{out['at_worst_leveraged']:.1%} in the 3x ETF at its worst")
    out["text"] = "; ".join(bits)
    return out


def load_trades(export_dir: Path) -> tuple[pd.DataFrame | None, str | None]:
    """The backtester's trade list (exports/trades/<run>.csv, named in trade_simulation.json), or None and why."""
    sim, why = _optional_json(Path(export_dir) / "trade_simulation.json")
    name = (sim or {}).get("trade_list")
    if not name:
        return None, why or "trade_simulation.json names no trade list"
    path = Path(export_dir).parent / name
    try:
        frame = pd.read_csv(path)
    except FileNotFoundError:
        return None, f"{name} not found"
    except (OSError, ValueError) as exc:
        return None, f"{name} unreadable ({str(exc)[:80]})"
    need = {"symbol", "signal", "exit", "pricing", "period", "signal_day", "mae", "net", "sessions"}
    if not need <= set(frame.columns):
        return None, f"{name} lacks {', '.join(sorted(need - set(frame.columns)))}"
    return frame, None


def _rule_rows(trades: pd.DataFrame, symbol: str, signal: str, exit_name: str, mode: str) -> pd.DataFrame:
    return trades[(trades["symbol"] == symbol) & (trades["signal"].map(_base) == _base(signal))
                  & (trades["exit"].map(_base) == _base(exit_name)) & (trades["pricing"] == mode)]


def drawdown_group(trades: pd.DataFrame | None, symbol: str, signal: str, exit_name: str, mode: str,
                   drawdown: float | None) -> dict:
    """Past trades of the same rule, exit and entry whose worst point reached this drawdown, and how many of them
    finished positive (spec step 2.6: the right comparison group, not the whole-trade MAE of all trades)."""
    if trades is None:
        return {"status": "unavailable"}
    if drawdown is None or drawdown >= 0:
        return {"status": "none", "drawdown": drawdown}
    rows = _rule_rows(trades, symbol, signal, exit_name, mode)
    out = {"status": "ok", "drawdown": drawdown}
    for period in ("development", "holdout"):
        part = rows[rows["period"] == period]
        reached = part[part["mae"] <= drawdown]
        out[period] = {"trades": int(len(part)), "reached": int(len(reached)),
                       "finished_positive": int((reached["net"] > 0).sum())}
    return out


def drawdown_text(group: dict) -> str:
    if group.get("status") != "ok":
        return "" if group.get("status") == "none" else "The backtester's trade list is unavailable, so there is no comparison group."
    dev, hold = group["development"], group.get("holdout") or {}
    if not dev["trades"]:
        return "No past trades of this rule in the trade list."
    if not dev["reached"]:
        text = f"None of its {dev['trades']} trades since 2010 went that far against: this is beyond every past worst point."
    else:
        text = (f"{dev['reached']} of its {dev['trades']} trades since 2010 went that far against; "
                f"{dev['finished_positive']} of those {dev['reached']} finished positive"
                + (" (a small group)" if dev["reached"] < TOO_FEW else "") + ".")
    if hold.get("trades"):
        text += f" 1993-2009: {hold['reached']} of {hold['trades']} went that far, {hold['finished_positive']} finished positive."
    return text


def analogs(trades: pd.DataFrame | None, symbol: str, signal: str, exit_name: str, mode: str, n: int = ANALOGS) -> list[dict]:
    """The last `n` trades of this setup in the trade list: signal date (to look up on the chart), result, worst point."""
    if trades is None:
        return []
    rows = _rule_rows(trades, symbol, signal, exit_name, mode).sort_values("signal_day").tail(n)
    return [{"signal_day": str(r.signal_day), "exit_day": str(getattr(r, "exit_day", "") or ""), "sessions": int(r.sessions),
             "net": float(r.net), "mae": float(r.mae), "period": str(r.period)} for r in rows.itertuples()][::-1]


# ---- sections -----------------------------------------------------------------------------------------------------

def _rules_in_play(plans: list[dict], sigs: list[dict]) -> list[dict]:
    """The rules the context tags are about: the plan's, or else the Leads that fired or are near their trigger."""
    if plans:
        return [{"symbol": p["symbol"], "signal": r["signal"], "exit": r["exit"], "mode": r["mode"], "short": r["short"]}
                for p in plans for r in p["rules"]]
    out = []
    for s in sigs:
        if not (s.get("fired") or s.get("near_trigger")):
            continue
        for e in s.get("evidence") or []:
            if e.get("verdict") == "Lead":
                out.append({"symbol": s["symbol"], "signal": s["signal"], "exit": e["exit"], "mode": e["mode"],
                            "short": f"{SHORT.get(s['signal'], s['label'])} ({ENTRY.get(e['mode'], e['mode'])})"})
    return out


def plans(state: dict, root: Path, sigs: list[dict], trades: pd.DataFrame | None = None) -> list[dict]:
    """One plan per ETF when its next-open Leads fired (spec step 1.4: several Leads on one close are one bet)."""
    latest, stance = state.get("latest_close"), state.get("stance") or {}
    if stance.get("direction") != "long" or not latest:
        return []
    limit = loss_limit(root)
    entry_day = (sessions_after(latest, 1) or [None])[0]
    grouped: dict[str, list[dict]] = {}
    for basis in stance.get("basis") or []:
        exit_name = next((k for k, v in signals.EXIT_LABELS.items() if v == basis.get("exit")), basis.get("exit"))
        sig = next((s for s in sigs if s["symbol"] == basis["symbol"] and s["label"] == basis["rule"]), {})
        card = next((c for c in sig.get("cards") or [] if c.get("exit") == exit_name), None)
        stop = (sessions_after(latest, TIME_STOP.get(exit_name, 10)) or [None])[-1]
        grouped.setdefault(basis["symbol"], []).append(
            {"rule": basis["rule"], "signal": sig.get("signal"), "short": SHORT.get(sig.get("signal"), basis["rule"]),
             "exit": exit_name, "mode": eligibility.ENTRY_MODE, "exit_rule": EXIT_TEXT.get(exit_name, basis.get("exit")),
             "time_stop": stop, "spread": spread(card),
             "analogs": analogs(trades, basis["symbol"], sig.get("signal"), exit_name, eligibility.ENTRY_MODE)})
    out = []
    for symbol, rules in grouped.items():
        sig = next((s for s in sigs if s["symbol"] == symbol), {})
        exits = sorted({r["exit"] for r in rules})
        longest = max(TIME_STOP.get(e, 10) for e in exits)
        window = holding_window(latest, longest)
        worst = min((r["spread"] or {}).get("worst_inside") or 0 for r in rules) or None
        lev = min(((r["spread"] or {}).get("leveraged") or {}).get("mae_worst") or 0 for r in rules) or None
        exit_close = sig.get("exit_close") if "close_above_sma5" in exits else None
        exit_lines = []
        for e in exits:
            stop = (sessions_after(latest, TIME_STOP.get(e, 10)) or [None])[-1]
            names = " and ".join(r["short"] for r in rules if r["exit"] == e)
            if e == "close_above_sma5":
                exit_lines.append((f"{names}: " if len(exits) > 1 else "")
                                  + f"a close above {_num(exit_close, '.2f')} on {_day(entry_day)} (the 5-day-average exit; "
                                    f"it is recomputed each day). Time stop: {_day(stop)}.")
            else:
                exit_lines.append((f"{names}: " if len(exits) > 1 else "") + f"the close on {_day(stop)} (5 sessions).")
        out.append({"symbol": symbol, "rules": rules, "one_bet": len(rules) > 1, "entry_day": entry_day,
                    "entry": f"the open on {_day(entry_day)}" if entry_day else "the next open",
                    "exit_close": exit_close, "exits": exits, "exit_lines": exit_lines,
                    "time_stop": window["to"] if window else None, "window": window,
                    "catalysts": catalysts(state, latest, window),
                    "close": sig.get("close"), "size": sizing(limit["fraction"], worst, lev),
                    "loss_at_limit": "set a loss limit" if not limit["fraction"] else f"{limit['fraction']:.2%} of the account",
                    "limit_reason": limit["reason"]})
    return out


def plan_callout(plan: dict, state: dict) -> dict:
    latest = state.get("latest_close")
    lv = ((state.get("levels") or {}).get("symbols") or {}).get(plan["symbol"]) or {}
    names = [r["short"] for r in plan["rules"]]
    text = (f"{plan['symbol']} closed at {_num(plan.get('close'), '.2f')} on {_day(latest)}"
            + (f" ({lv['change_1d']:+.1%})" if lv.get("change_1d") is not None else "") + ". "
            + " and ".join(names) + (" fired; both are Leads at the next open." if len(names) == 2 else
                                     " fired; all are Leads at the next open." if len(names) > 2 else
                                     " fired; it is a Lead at the next open."))
    if plan["one_bet"]:
        text += " They are oversold rules on the same ETF and close: one bet, one size."
    text += f" Entry: {plan['entry']}. Exit: " + " ".join(plan["exit_lines"])
    text += " " + ". ".join(spread_text(r["short"], r["mode"], r["spread"]) for r in plan["rules"]) + "."
    text += f" Size: {plan['size']['text']}."
    return _callout("act", text, "Daily thesis stance, backtester evidence cards")


def rule_trades(state: dict, trades: pd.DataFrame | None) -> list[dict]:
    """Open trades of every Lead, the stance's or not (spec step 2.6), each against its drawdown comparison group."""
    paper = [t for t in (state.get("paper_book") or {}).get("trades") or [] if t.get("status") in ("open", "pending")]
    out = []
    for t in state.get("rule_trades") or []:
        taken = any(p.get("instrument") == t["symbol"] and p.get("rule") == t["signal"] and p.get("exit") == t["exit"]
                    and p.get("entry_mode") == t["entry_mode"] and p.get("signal_day") == t["signal_day"] for p in paper)
        group = drawdown_group(trades, t["symbol"], t["signal"], t["exit"], t["mode"], t.get("worst_so_far"))
        out.append({**t, "short": SHORT.get(t["signal"], t["rule"]), "taken_by_stance": taken,
                    "label": "the stance's paper trade" if taken else "rule trade, not a stance",
                    "drawdown_group": group, "drawdown_text": drawdown_text(group)})
    return out


def rule_trade_callout(t: dict) -> dict:
    exit_text = (f"a close above {t['exit_above']:.2f}" if t.get("exit_above") is not None else
                 f"the close on {_day(t['time_stop'])}" if t["exit"] == "hold_5" else "its 5-day-average exit")
    text = (f"{t['label'][0].upper()}{t['label'][1:]}: {t['symbol']} {t['short']} {ENTRY.get(t['mode'], t['mode'])}, in since "
            f"{_day(t['signal_day'])} at {_num(t.get('entry_price'), '.2f')}, now {_num(t.get('gross'), '+.1%')}"
            + (f" (low {t['worst_so_far']:+.1%})" if t.get("worst_so_far") is not None else "") + ". "
            + (t["drawdown_text"] + " " if t.get("drawdown_text") else "")
            + f"Exit: {exit_text}. Time stop: {_day(t['time_stop'])}.")
    return _callout("watch", text, "this app's copy of the exit rules; backtester trade list")


def today(state: dict, root: Path, trades: pd.DataFrame | None = None, filters: dict | None = None) -> dict:
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
                       # signed like the % distance: negative when the trigger close is below today's close
                       "distance_atr": -s["near_atr"] if s.get("near_atr") is not None else None,
                       "near_basis": s.get("near_basis"),
                       "next_open_lead": bool(leads), "next_open_verdicts": verdicts})
        name = f"{s['symbol']} {s['label']}"
        if s.get("fired") and not leads:
            callouts.append(_callout("info", f"{name} fired at the {latest} close, but buying at the next open is not "
                                     f"a Lead ({', '.join(verdicts) or 'untested'}), so it is not a setup now.",
                                     "Daily thesis: registered signals"))
        elif near and leads:
            atr = f", {s['near_atr']:.1f} ATR(14)" if s.get("near_atr") is not None else ""
            callouts.append(_callout("watch", f"{name} fires if {s['symbol']} closes at or below "
                                     f"${s['trigger_close']:.2f} ({s['trigger_close'] / s['close'] - 1:+.1%}{atr} from "
                                     f"${s['close']:.2f}). It is a next-open Lead.", "Daily thesis: registered signals"))
    plan = plans(state, root, sigs, trades)
    callouts = [plan_callout(p, state) for p in plan] + callouts
    open_rule = rule_trades(state, trades)
    callouts += [rule_trade_callout(t) for t in open_rule
                 if not t["taken_by_stance"] and t.get("status") == "open" and t.get("worst_so_far") is not None]
    rules = _rules_in_play(plan, sigs)
    callouts += context_callouts(state, plan, rules, filters)
    return {"latest_close": latest, "stance": {k: stance.get(k) for k in ("direction", "headline", "status")},
            "setups": setups, "plan": plan, "rule_trades": open_rule, "rules_in_play": rules, "callouts": callouts}


def context_callouts(state: dict, plan: list[dict], rules: list[dict], filters: dict | None) -> list[dict]:
    """The holding window, VIX, trend and gap callouts, each tagged by its registered filter test (spec 1.2-1.3)."""
    out, latest = [], state.get("latest_close")
    ctx = context_state(state, latest)
    window = None
    if plan:
        window = max((p["window"] for p in plan if p.get("window")), key=lambda w: w["to"], default=None)
    for t in state.get("rule_trades") or []:
        if t.get("status") == "open" and t.get("time_stop") and (window is None or t["time_stop"] > window["to"]):
            window = holding_window(latest, len([d for d in sessions_after(latest, 40) if d <= t["time_stop"]]))
    label = "In the holding window"
    if window is None:
        window = holding_window(latest, max(TIME_STOP.values()))
        label = f"In the next {max(TIME_STOP.values())} sessions (the longest holding window)"
    found = catalysts(state, latest, window)
    if window:
        release = tags_for("release_within_5_sessions", rules, filters)
        text = (f"{label} ({_day(window['from'])} to {_day(window['to'])}): "
                + ("; ".join(f"{c['what']} on {_day(c['date'])}" for c in found) if found else "no scheduled release, "
                   "mega-cap earnings, holiday or half day") + ".")
        if ctx["release"]["active"]:
            text += f" A release within 5 sessions: {phrase(release)}."
        elif any(c["kind"] == "release" for c in found):
            text += (" The release filter tested scheduled releases in the 5 sessions after the signal; these come "
                     "later, so that test does not apply to them.")
        out.append(_callout("watch" if found else "info", text, "Daily thesis events and earnings; exchange calendar",
                            release if ctx["release"]["active"] else None))
    vol = (state.get("regime") or {}).get("volatility") or {}
    if vol.get("vix") is not None:
        inverted = (vol.get("term_ratio") or 0) > 1
        level_tags, term_tags = tags_for("vix_level", rules, filters), tags_for("vix_term_structure", rules, filters)
        text = (f"VIX {vol['vix']:.1f}" + (f", above VIX3M ({vol['vix3m']:.1f})" if inverted and vol.get("vix3m") else
                                           f", below VIX3M ({vol['vix3m']:.1f})" if vol.get("vix3m") else ""))
        if vol["vix"] >= 25 or inverted:
            text += ": moves run larger, which matters for size."
        else:
            text += "."
        if rules:
            text += (f" For taking or skipping the setup: VIX 20 or higher: {phrase(level_tags)}. "
                     f"VIX above VIX3M: {phrase(term_tags)}.")
        out.append(_callout("watch" if vol["vix"] >= 25 or inverted else "info", text, "Cboe VIX and VIX3M; backtester filter tests",
                            level_tags + term_tags))
    if ctx["spy_trend"]["active"] and rules:
        trend_tags = tags_for("spy_200d_trend", rules, filters)
        out.append(_callout("info", f"{ctx['spy_trend']['detail']}. SPY below its 200-day average: {phrase(trend_tags)}.",
                            "Daily thesis trend; backtester filter tests", trend_tags))
    next_open = [r for r in rules if r["mode"] == "etf_next_open"]
    if plan and next_open:
        gap_tags = tags_for("gap_at_next_open", next_open, filters)
        out.append(_callout("info", f"If the next open is 0.5% or more above the {latest} close: {phrase(gap_tags)}.",
                            "backtester filter tests (gap at the next open)", gap_tags))
    if state.get("next_entry_et") and latest:
        gap = (pd.Timestamp(state["next_entry_et"]).tz_localize(None).normalize() - pd.Timestamp(latest)).days
        if gap >= 2:  # 1 is an ordinary weeknight
            out.append(_callout("watch", f"A weekend or holiday comes before the next open "
                                f"({pd.Timestamp(state['next_entry_et']):%a %b %d}): the reopening gap is larger.",
                                "Exchange calendar"))
    return out


def risk_callouts(state: dict) -> list[dict]:
    """v1's name for the context callouts (kept for callers); now tagged and over the holding window."""
    return context_callouts(state, [], [], None)


def levels(state: dict) -> list[dict]:
    """Where price sits against the levels that matter, plus a copyable list for chart alerts (spec step 3.9)."""
    trend = ((state.get("regime") or {}).get("trend")) or {}
    computed = (state.get("levels") or {}).get("symbols") or {}
    out = []
    for symbol in LEVELS:
        mine = [s for s in state.get("signals") or [] if s.get("symbol") == symbol]
        if not mine and symbol not in trend and symbol not in computed:
            continue
        t, lv = trend.get(symbol) or {}, computed.get(symbol) or {}
        boll = next((s for s in mine if s.get("signal") == "bollinger_lower_close"), {})
        row = {"symbol": symbol, "close": lv.get("close") or t.get("close") or (mine[0].get("close") if mine else None),
               "triggers": [{"rule": s["label"], "short": SHORT.get(s["signal"], s["label"]),
                             "close_at_or_below": s.get("trigger_close")} for s in mine],
               "lower_band": boll.get("value"), "sma5": lv.get("sma5") or (mine[0].get("sma5") if mine else None),
               "exit_close": lv.get("exit_close") or (mine[0].get("exit_close") if mine else None),
               "sma20": lv.get("sma20"), "sma50": lv.get("sma50") or t.get("sma50"),
               "sma200": lv.get("sma200") or t.get("sma200"), "atr14": lv.get("atr14"),
               "swing_high": lv.get("swing_high"), "swing_low": lv.get("swing_low")}
        marks = [(row["exit_close"], "exit close (5-day-average exit)"), (row["lower_band"], "lower Bollinger band"),
                 (row["sma5"], "5-day average"), (row["sma20"], "20-day average"), (row["sma50"], "50-day average"),
                 (row["sma200"], "200-day average")]
        marks += [(x["close_at_or_below"], f"{x['short']} fires at or below") for x in row["triggers"]]
        for key, name in (("swing_high", "swing high"), ("swing_low", "swing low")):
            if row[key]:
                marks.append((row[key]["price"], f"{name} {row[key]['date']}"))
        marks = sorted([(float(p), n) for p, n in marks if p], reverse=True)
        row["copy"] = f"{symbol}: " + "; ".join(f"{p:.2f} {n}" for p, n in marks)
        out.append(row)
    return out


def regime_lines(state: dict, rules: list[dict], filters: dict | None) -> list[list[dict]]:
    """The regime in two lines (spec step 3.9): trend and volatility; breadth and credit. Each item tagged."""
    reg = state.get("regime") or {}
    trend, vol, breadth = reg.get("trend") or {}, reg.get("volatility") or {}, reg.get("breadth") or {}
    first, second = [], []
    bits = [f"{s} {trend[s]['vs_sma200']:+.1%}" for s in ("SPY", "QQQ") if (trend.get(s) or {}).get("vs_sma200") is not None]
    if bits:
        first.append({"item": "Trend", "text": "against the 200-day average: " + ", ".join(bits),
                      "tags": tags_for("spy_200d_trend", rules, filters)})
    if vol.get("vix") is not None:
        side = "above" if (vol.get("term_ratio") or 0) > 1 else "below"
        first.append({"item": "Volatility", "text": f"VIX {vol['vix']:.1f}, {side} VIX3M {vol.get('vix3m') or 0:.1f}",
                      "tags": tags_for("vix_level", rules, filters) + tags_for("vix_term_structure", rules, filters)})
    if breadth.get("relative_20d") is not None:
        second.append({"item": "Breadth", "text": f"equal-weight S&P (RSP) {breadth['relative_20d']:+.1%} against SPY over 20 sessions",
                       "tags": [{"rule": "all", "tag": "untested", "text": "untested (no registered test)"}]})
    credit = next((c for c in reg.get("credit") or [] if c.get("series") == "BAA10Y" and c.get("value") is not None), None)
    if credit:
        rank = round((credit.get("percentile") or 0) * 100)
        suffix = "th" if 10 <= rank % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(rank % 10, "th")
        second.append({"item": "Credit", "text": f"Baa spread {credit['value']:.2f} points ({rank}{suffix} "
                                                 f"percentile since {str(credit.get('since') or '')[:4]}), "
                                                 f"{credit.get('change_1m') or 0:+.2f} in a month",
                       "tags": [{"rule": "all", "tag": "untested", "text": "untested (the credit filter is not registered)"}]})
    return [line for line in (first, second) if line]


def what_would_change(state: dict, plan: list[dict], sigs: list[dict]) -> list[str]:
    out = []
    for p in plan:
        if p.get("exit_close") is not None:
            out.append(f"{p['symbol']}: a close above {p['exit_close']:.2f} on {_day(p['entry_day'])} ends the trade "
                       "(the 5-day-average exit); the level moves each day.")
        out.append(f"{p['symbol']}: the time stop on {_day(p['time_stop'])} ends it in any case.")
        out.append("If the backtester's weekly run rates a rule in this plan \"Forward below band\", the stance for "
                   "it turns flat.")
        out.append("The rules have no stop: a \"wrong if\" level is yours to set, in the thesis below.")
    if not plan:
        for s in sigs:
            if s.get("fired") or not s.get("trigger_close") or not eligibility.open_leads(s):
                continue
            atr = f", {s['near_atr']:.1f} ATR(14)" if s.get("near_atr") is not None else ""
            out.append(f"{s['symbol']} {SHORT.get(s['signal'], s['label'])} fires at a close at or below "
                       f"{s['trigger_close']:.2f} ({s['trigger_close'] / s['close'] - 1:+.1%}{atr}).")
    return out


def thesis(state: dict, plan: list[dict], rules: list[dict], filters: dict | None, sigs: list[dict]) -> dict:
    """The information in the order a view is built, and a thesis pre-filled from the plan to save as a call."""
    latest = state.get("latest_close")
    window = max((p["window"] for p in plan if p.get("window")), key=lambda w: w["to"], default=None) \
        or holding_window(latest, max(TIME_STOP.values()))
    prefill = None
    if plan:
        p = plan[0]
        context = []
        ctx = context_state(state, latest)
        for item in CONTEXT:
            state_now = ctx.get(item["id"]) or {}
            if state_now.get("active"):
                context.append(f"{item['label']} ({state_now.get('detail')}): {phrase(tags_for(item['test'], rules, filters))}")
        rule_names = " + ".join(r["short"] for r in p["rules"])
        reason = (f"Take the {p['symbol']} setup: {rule_names} fired at the {latest} close (tested edge"
                  + ("s" if len(p["rules"]) > 1 else "") + f", one bet). Entry: {p['entry']}. Exit: "
                  + " ".join(p["exit_lines"]) + (" Context: " + "; ".join(context) + "." if context else ""))
        prefill = {"instrument": p["symbol"], "direction": "long", "horizon_sessions": p["window"]["sessions"] if p.get("window") else 10,
                   "basis": ["signal"], "reason": reason[:1500], "exit_side": "below", "exit_price": None,
                   "invalidation": "", "context": {"suggestion": f"review plan {p['symbol']} {rule_names}",
                                                   "page_as_of": state.get("as_of"), "latest_close": latest},
                   "note": "The rules have no stop. Type your own \"wrong if\" close below which the thesis is wrong; "
                           "it is recorded before entry and never changed. The call links to the page's opportunity "
                           "ids itself and records whether it takes, vetoes or overrides the rule."}
    return {"regime": regime_lines(state, rules, filters), "window": window,
            "catalysts": catalysts(state, latest, window), "changes": what_would_change(state, plan, sigs),
            "analogs": [{"symbol": p["symbol"], "rule": r["short"], "mode": r["mode"], "exit": r["exit"], "rows": r["analogs"]}
                        for p in plan for r in p["rules"]],
            "prefill": prefill}


# ---- edges, year, record, queue ------------------------------------------------------------------------------------

def _cards_for(s: dict) -> list[dict]:
    return list(s.get("cards") or []) + list(s.get("close_cards") or [])


def year_table(state: dict) -> dict:
    """What to expect over a year, per Lead pricing (spec step 2.8), from the backtester's export and cards."""
    rows = []
    for s in state.get("signals") or []:
        for e in s.get("evidence") or []:
            if e.get("verdict") != "Lead":
                continue
            dev = e.get("development") or {}
            card = next((c for c in _cards_for(s) if c.get("exit") == e["exit"] and c.get("entry") == e["mode"]), {})
            rows.append({"symbol": s["symbol"], "rule": SHORT.get(s["signal"], s["label"]), "exit": e.get("exit_label") or e["exit"],
                         "entry": ENTRY.get(e["mode"], e["mode"]), "trades": dev.get("trades"),
                         "trades_per_year": card.get("trades_per_year"), "mean_net": dev.get("mean_net"),
                         "exposure": dev.get("exposure"), "cagr": (dev.get("strategy") or {}).get("cagr"),
                         "per_volatility": dev.get("per_volatility"), "index_per_volatility": dev.get("index_per_volatility")})
    return {"rows": rows,
            "note": "From the backtester's development window (2010 to its end date), 2 bp round trip, cash earns 0. "
                    "Return per unit of volatility is the annualised mean over the annualised volatility of daily "
                    "returns; at the same total volatility the higher one earns more. For every Lead, QQQ or SPY held "
                    "is higher (the backtester's 2026-11-18 review: QQQ Bollinger at the next open +4.77% a year "
                    "against +9.17% for QQQ held at the same volatility). So the case for a Lead is its expected result "
                    "per trade, as an add-on to a held position, an overlay, or the 3x ETF during the trade; it does not "
                    "replace holding."}


def edge_health(state: dict, filters: dict | None, open_rule: list[dict]) -> list[dict]:
    """Per Lead: development excess with its 90% interval, 1993-2009, the forward record against its band, open
    rule trades that will join it, and the same-volatility test (spec step 4.11)."""
    out = []
    for s in state.get("signals") or []:
        for c in _cards_for(s):
            if c.get("verdict") not in ("Lead", eligibility.FORWARD_BELOW):
                continue
            mode = c.get("entry")
            same_vol = filter_test(filters, s["symbol"], s["signal"], c["exit"], mode, "volatility_matched_baseline")
            joining = [t for t in open_rule if t["symbol"] == s["symbol"] and t["signal"] == s["signal"]
                       and t["exit"] == c["exit"] and t["mode"] == mode]
            out.append({"symbol": s["symbol"], "rule": SHORT.get(s["signal"], s["label"]), "exit": c.get("exit_label") or c["exit"],
                        "entry": ENTRY.get(mode, mode), "verdict": c.get("verdict"), "trades": c.get("trades"),
                        "small": bool(c.get("trades") is not None and c["trades"] < SMALL_SAMPLE),
                        "excess": c.get("excess"), "excess_ci90": c.get("excess_ci90"), "holdout": c.get("holdout"),
                        "forward": c.get("forward"), "open_joining": len(joining),
                        "same_volatility": None if not same_vol else
                        {k: same_vol.get(k) for k in ("diff", "ci90", "p", "q", "label")}})
    return out


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
        b["judge"] = "too few to judge" if b["scored"] < TOO_FEW else None
        del b["returns"]
    # The rule against you, by opportunity id (spec step 4.12): every long opportunity the stance logged, and
    # whether a call took, vetoed or overrode it, or none was recorded.
    called = {i: c.get("relation") for c in calls for i in c.get("opportunity_ids") or []}
    opportunities = [(r.get("latest_close"), o) for r in (state.get("stance_log") or {}).get("records") or []
                     for o in r.get("opportunities") or []]
    long_ids = [o["id"] for _, o in opportunities if o.get("disposition") == "long"]
    versus = {"rule_long": len(long_ids), "no_call": sum(1 for i in long_ids if i not in called),
              "by_relation": {}}
    for i in long_ids:
        if i in called:
            versus["by_relation"][called[i]] = versus["by_relation"].get(called[i], 0) + 1
    by_basis = {str(v.get("basis")): {"scored": v.get("scored"), "mean_call_return": v.get("mean_call_return"),
                                      "mean_versus_always_long": v.get("mean_versus_always_long"),
                                      "judge": "too few to judge" if (v.get("scored") or 0) < TOO_FEW else None}
                for v in (state.get("calls") or {}).get("by_basis") or [] if isinstance(v, dict) and v.get("basis")}
    directional = [c for c in calls if c.get("direction") in ("long", "short")]
    process = {"directional_calls": len(directional),
               "with_exit_level": sum(1 for c in directional if c.get("exit_level")),
               "took_the_plan": sum(1 for c in calls if c.get("relation") == "take"),
               "note": "An exit level is recorded with the call, before entry, and can't change afterwards."}
    missed_closes = (state.get("stance_log") or {}).get("missed_closes") or []
    missed_decisions = (state.get("ops") or {}).get("missed_decisions") or []
    callouts = [_callout("act" if line.get("action") in ("enter", "exit") else "watch", line.get("text", ""),
                         "Daily thesis: paper ticket") for line in book.get("ticket") or []]
    if missed_closes:
        callouts.append(_callout("info", f"{len(missed_closes)} close(s) had no stance recorded before the next open: "
                                 + ", ".join(missed_closes[-6:]) + ". Leave the laptop asleep or on, not shut down.",
                                 "stance log (missed records)"))
    return {"open_trades": open_trades, "calls_by_relation": against, "calls": len(calls), "versus_rule": versus,
            "by_basis": by_basis, "process": process,
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
    tests_due = [  # spec step 4.13: the tests that are due and what each waits for
        {"test": "IWM's first 1993-2009 look", "waits_for": "the backtester's next registered study run (IWM's daily "
                                                             "history goes back to 2000 here since 2026-11-18)"},
        {"test": "Credit filter", "waits_for": "registration in the backtester (not registered yet)"},
        {"test": "Opening-range tests (experiment A)", "waits_for": "20 complete sampled days of minute history "
                                                                    "(the Intraday tab counts them)"},
        {"test": "Gap filter (unresolved: q 0.11, 1993-2009 disagreed)",
         "waits_for": "forward trades after next-open gaps; the backtester does not export a forward count for it yet"},
    ]
    return {"by_stage": by_stage, "counts": (state.get("ideas") or {}).get("counts") or {}, "forward_checks": due,
            "tests_due": tests_due, "callouts": callouts}


def changes(state: dict, root: Path, export_dir: Path | None = None, filters: dict | None = None,
            filters_why: str | None = None) -> dict:
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
    if filters is None and filters_why is None:
        filters, filters_why = load_filters(export_dir)
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
            "filter_tests": {"status": "ok" if filters else filters_why, "generated_at": (filters or {}).get("generated_at"),
                             "by_label": by_label, "notable": notable, "count": len(tests)},
            "problems": [{k: r.get(k) for k in ("label", "state", "last", "detail")} for r in problems]}


# ---- timing ---------------------------------------------------------------------------------------------------------

def mode_for(now) -> str:
    """Pre-close (the 30 minutes before a session's close), weekly (Saturday and Sunday) or evening (other times)."""
    t = pd.Timestamp(now)
    t = t.tz_localize(NY) if t.tzinfo is None else t.tz_convert(NY)
    if t.day_of_week >= 5:
        return "weekly"
    from .preclose import window
    span = window(t.tz_localize(None).normalize())
    minutes = t.hour * 60 + t.minute
    return "preclose" if span and span[0] <= minutes < span[1] else "evening"


def _live_bars(root: Path, day: str) -> dict:
    """The latest regular-session minute bar per symbol from that session's live journal (Yahoo, indicative)."""
    from intraday.store import live_folder, read_events
    path = live_folder(root) / f"{day}.jsonl"
    if not path.exists():
        return {}
    latest = {}
    for event in read_events(path):
        bar = event.get("bar") or {}
        if event.get("type") == "bar" and bar.get("symbol") and bar.get("close"):
            if bar["symbol"] not in latest or bar["timestamp"] >= latest[bar["symbol"]]["timestamp"]:
                latest[bar["symbol"]] = bar
    return latest


def preclose_live(root: Path, now=None) -> dict:
    """Pre-close view (spec step 5.14): the latest minute bar as the estimated close, against the triggers of the
    close-entry Leads. Watch only: it never changes the stance and writes nothing."""
    from . import data, preclose
    now = pd.Timestamp.now(tz=NY) if now is None else pd.Timestamp(now).tz_convert(NY)
    day = now.tz_localize(None).normalize()
    out = {"mode": mode_for(now), "as_of": now.isoformat(), "date": f"{day:%Y-%m-%d}", "rows": [], "bars": {}}
    span = preclose.window(day)
    if not span:
        return {**out, "status": "no_session", "detail": "No session today."}
    out["window_et"] = f"{span[0] // 60}:{span[0] % 60:02d}-{span[1] // 60}:{span[1] % 60:02d}"
    bars = _live_bars(root, out["date"])
    if not bars:
        return {**out, "status": "no_bars", "detail": "No live minute bars today yet (the live poller runs from the open)."}
    etfs = {k: f[f.index < day] for k, f in data.etfs(root, now).items()}
    payload, _ = signals.load_export()
    prices = {s: float(b["close"]) for s, b in bars.items()}
    rows = preclose.evaluate(etfs, prices, day, payload)
    for symbol, b in bars.items():
        stamp = pd.Timestamp(b["timestamp"]) + pd.Timedelta(seconds=60)
        out["bars"][symbol] = {"price": float(b["close"]), "bar_end_et": stamp.tz_convert(NY).isoformat(),
                               "age_seconds": max(0, int((now - stamp).total_seconds())),
                               "basis": b.get("availability_basis")}
    out["rows"] = [r for r in rows if r.get("close_lead_exits")]
    return {**out, "status": "ok", "detail": "Estimated close = the latest one-minute bar. Watch only: the stance "
                                             "takes no close entry, and whether it ever should is your separate decision."}


# ---- the page -------------------------------------------------------------------------------------------------------

def build(state: dict, root: Path, export_dir: Path | None = None, now=None) -> dict:
    export_dir = Path(export_dir or signals.export_path().parent)
    filters, filters_why = load_filters(export_dir)
    trades, trades_why = load_trades(export_dir)
    t = today(state, root, trades, filters)
    sigs = [s for s in state.get("signals") or [] if s.get("symbol") in EVIDENCE]
    sections = {"today": t, "levels": levels(state), "thesis": thesis(state, t["plan"], t["rules_in_play"], filters, sigs),
                "changes": changes(state, root, export_dir, filters, filters_why), "record": record(state),
                "queue": queue(state), "year": year_table(state), "edges": edge_health(state, filters, t["rule_trades"])}
    order = {"act": 0, "watch": 1, "info": 2}
    top = sorted([c for key in ("today", "changes", "record") for c in sections[key]["callouts"]],
                 key=lambda c: order.get(c["level"], 3))
    built = pd.Timestamp(now) if now is not None else (pd.Timestamp(state["as_of"]) if state.get("as_of") else pd.Timestamp.now(tz=NY))
    return {"as_of": state.get("as_of"), "latest_close": state.get("latest_close"), "mode": mode_for(built),
            "headline": top[:12], **sections,
            "sources": {"filter_tests": "ok" if filters else filters_why, "trade_list": "ok" if trades is not None else trades_why},
            "tag_names": TAG_NAMES,
            "undecided": ["A maximum loss per trade (the plan shows \"set a loss limit\" until you set one).",
                          "Whether QQQ trades are add-ons to a held position or standalone."]}
