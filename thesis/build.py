"""Assemble and render the Daily thesis tab (thesis.html, thesis_state.json). Read-only: never collects data.

The stance rules only use registered evidence. Version 2 (2026-11-13; version 1 was fixed 2026-11-08), shared with
the stance log through thesis/eligibility.py:
- Long candidate: a registered oversold rule fired at the latest close on SPY or QQQ, and the backtester rated
  its *next-open* pricing a Lead. What "Lead" means is the backtester's: since 2026-11-14 its export uses Lead v2
  (the average trade beats every same-length trade, judged by resampling the rule's trades by calendar quarter,
  corrected for testing many rules, and CAGR above buy-and-hold scaled to time in the market and volatility, in
  both periods); the export's own `verdict_definition` is shown on the page. Earlier exports used v1 (a
  random-entry percentile and time-matched buy-and-hold). Stance rules version 1 counted any Lead pricing,
  including "buy at the signal close", which has passed when the page is read.
- Flat: nothing with a next-open Lead fired. A rule that fired with only a closing-price Lead is listed as
  "fired, but not a setup now". The page lists the closes that would fire each next-open Lead rule.
  Since the backtester's Lead v3 (2026-11-18), a rule whose forward record fell below its band is rated
  "Forward below band", not Lead: if it fires, the page says so (status "forward_below_band"); otherwise it is a
  caution, so a rule never drops out of the call silently.
- No call: the evidence can't be used (missing, unreadable, incomplete, mismatched, unchecked or too old).
- Short: never suggested. No short rule has evidence (the rally shorts failed the 1993-2009 holdout).
The user makes the actual call and records it in the call log.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pandas as pd

from . import (alfred, archive, calls, data, earnings, earnings_calendar, eligibility, evidence_cards, journal, ledger,
               macro, morning, movers, news, ops, paper_book, preclose, regime, releases, risk, signals, stance_log)

TEMPLATE = Path(__file__).with_name("template.html")
MACRO_TEMPLATE = Path(__file__).with_name("macro_template.html")
SCHEMA = 2  # 2 (2026-11-13): stance direction "none", evidence_check, ops, journal, ideas


def _sessions_after(start: pd.Timestamp, count: int) -> list[pd.Timestamp]:
    """The next `count` weekdays after `start` (an approximation of sessions: holidays aren't excluded)."""
    return list(pd.bdate_range(start + pd.Timedelta(days=1), periods=count))


SHORT_NOTE = "Short is never suggested: no registered short rule has evidence."


def _close_only_note(signal: dict, latest: str | None) -> str:
    """Why a fired rule is not a setup now: only its closing-price entry was rated a Lead."""
    later = sorted({e.get("verdict", "?") for e in signal.get("evidence") or [] if e.get("mode") == eligibility.ENTRY_MODE})
    return (f"{signal['symbol']} · {signal['label']} fired at the {latest} close. Its tested entry was that close, "
            f"which has passed; buying at the next open was rated {' / '.join(later) or 'untested'}, so it is not a setup now.")


def _forward_below_note(signal: dict, row: dict, latest: str | None, fired: bool) -> str:
    """A Lead the backtester demoted (Lead v3) because its forward trades fell below its development band."""
    fwd = row.get("forward") or {}
    detail = ""
    if all(isinstance(fwd.get(k), (int, float)) for k in ("trades", "mean_excess", "band_lower")):
        detail = (f" ({fwd['trades']} trades signalled after {fwd.get('since') or 'its development window'}: average "
                  f"excess {fwd['mean_excess']:+.2%} a trade, below the band's floor of {fwd['band_lower']:+.2%})")
    name = f"{signal['symbol']} · {signal['label']} ({row.get('exit_label') or row.get('exit')})"
    head = f"{name} fired at the {latest} close, but" if fired else f"{name}:"
    return (f"{head} the backtester now rates buying at the next open \"{eligibility.FORWARD_BELOW}\" instead of "
            f"Lead{detail}. Its forward record fell short of its history, so it no longer counts as a setup.")


def stance(sig: list[dict], reg: dict, earn: dict, latest: str | None, check: dict | None = None,
           entry_passed: bool = False) -> dict:
    """The page's call. `check` is eligibility.evidence_check(...); None means the evidence is taken as usable."""
    check = check if check is not None else {"usable": True}
    _leads = eligibility.open_leads
    fired = [s for s in sig if s["fired"] and _leads(s)]
    close_only = [_close_only_note(s, latest) for s in sig if s["fired"] and eligibility.close_only_leads(s)]
    # Lead v3: a fired rule whose only next-open verdict is "Forward below band" is listed with the fired-but-not-a-
    # setup rules; any other demoted pricing (not fired, or beside a remaining Lead) is a caution, so it is never silent.
    demoted_fired = [_forward_below_note(s, e, latest, True) for s in sig if s["fired"] and not _leads(s)
                     for e in eligibility.forward_below(s)]
    demoted_other = [_forward_below_note(s, e, latest, False) for s in sig if not (s["fired"] and not _leads(s))
                     for e in eligibility.forward_below(s)]
    close_only = demoted_fired + close_only
    window = _sessions_after(pd.Timestamp(latest), 10) if latest else []
    window_end = f"{window[-1]:%Y-%m-%d}" if window else None
    events_inside = [e for e in reg["events"].get("upcoming", []) if window_end and e["date"] <= window_end]
    earnings_inside = [r for r in earn.get("rows", []) if r.get("next_date") and window_end
                       and latest < r["next_date"] <= window_end]
    common = []
    if events_inside:
        common.append("Scheduled inside the next 10 sessions: " + "; ".join(f"{e['label']} {e['date']}" for e in events_inside) + ".")
    if earnings_inside:
        common.append("Mega-cap earnings inside the next 10 sessions: " + "; ".join(f"{r['name']} {r['next_date']}" for r in earnings_inside) + ".")
    vol = reg["volatility"]
    if vol.get("term_ratio") and vol["term_ratio"] > 1:
        common.append(f"VIX term structure is inverted ({vol['vix']:.1f} vs {vol['vix3m']:.1f} for 3 months), a stress "
                      "reading. Not part of any registered rule, so it isn't scored here.")
    if check.get("warning"):
        common.append(check["warning"])
    common.extend(check.get("notes") or [])  # e.g. a tolerated rounding tie in the date cross-check
    common.extend(demoted_other)
    if not check.get("usable", True):
        return {"direction": "none", "status": "evidence_unavailable",
                "headline": "No call: the backtested evidence can't be used",
                "reason": (check.get("reason") or "The backtester's evidence is unavailable.")
                + " The page shows no stance rather than guess. Regime and events below are context only.",
                "basis": [], "cautions": common, "exit": [], "changes": [], "close_only": [],
                "short_note": SHORT_NOTE}
    if not fired:
        changes = []
        for s in sig:
            if _leads(s) and s["trigger_close"]:
                changes.append({"symbol": s["symbol"], "rule": s["label"], "close_at_or_below": s["trigger_close"],
                                "distance": s["trigger_close"] / s["close"] - 1})
        if demoted_fired:
            return {"direction": "flat", "status": "forward_below_band",
                    "headline": f"Flat: a rule fired at the {latest} close, but its forward record fell below its band",
                    "reason": "The backtester no longer rates the rule that fired a Lead for buying at the next open: "
                              "its trades since its development window ended fell below the range its history "
                              "allowed. Regime and events below are context only.",
                    "basis": [], "cautions": common, "exit": [], "changes": changes, "close_only": close_only,
                    "short_note": SHORT_NOTE}
        if close_only:
            return {"direction": "flat", "status": "close_only_setup",
                    "headline": f"Flat: a rule fired at the {latest} close, but its tested entry has passed",
                    "reason": "No rule that fired is a backtested Lead for buying at the next open. Regime and "
                              "events below are context only.",
                    "basis": [], "cautions": common, "exit": [], "changes": changes, "close_only": close_only,
                    "short_note": SHORT_NOTE}
        return {"direction": "flat", "status": "no_registered_setup",
                "headline": f"Flat: no registered setup at the {latest} close",
                "reason": "None of the backtester's Lead rules fired. Regime and events below are context only.",
                "basis": [], "cautions": common, "exit": [], "changes": changes, "close_only": [],
                "short_note": SHORT_NOTE}
    basis, exits = [], []
    for s in fired:
        for e in _leads(s):
            dev, hold = e["development"], e["holdout"] or {}
            # Lead v2 judges against buy-and-hold scaled to time in the market and volatility ("risk_matched");
            # a v1 export only has the time-matched benchmark ("matched").
            bench = lambda r: r.get("risk_matched") or r.get("matched") or {}  # noqa: E731
            basis.append({"symbol": s["symbol"], "rule": s["label"], "exit": e["exit_label"], "mode": e["mode_label"],
                          "dev_trades": dev["trades"], "dev_win_rate": dev.get("win_rate"), "dev_mean_net": dev.get("mean_net"),
                          "dev_random_percentile": dev.get("random_percentile"),
                          "dev_excess": (dev.get("v2") or {}).get("mean_excess"), "dev_p": (dev.get("v2") or {}).get("p"),
                          "dev_quarters": (dev.get("v2") or {}).get("quarters"), "q": e.get("q"),
                          "holdout_p": (hold.get("v2") or {}).get("p"), "verdict_v1": e.get("verdict_v1"),
                          "benchmark": "risk_matched" if dev.get("risk_matched") else "matched",
                          "dev_per_drawdown": dev["strategy"].get("return_per_drawdown"),
                          "dev_matched_per_drawdown": bench(dev).get("return_per_drawdown"),
                          "dev_max_drawdown": dev["strategy"].get("max_drawdown"), "dev_avg_loss": dev.get("avg_loss"),
                          "holdout_trades": hold.get("trades"), "holdout_win_rate": hold.get("win_rate"),
                          "holdout_mean_net": hold.get("mean_net"),
                          "holdout_per_drawdown": (hold.get("strategy") or {}).get("return_per_drawdown"),
                          "holdout_matched_per_drawdown": bench(hold).get("return_per_drawdown")})
        if any(e["exit"] == "close_above_sma5" for e in _leads(s)):
            exits.append(f"{s['symbol']}: the first close above its 5-day average (about ${s['sma5']:.2f} now; it moves "
                         "daily) or after 10 sessions, whichever comes first.")
        if any(e["exit"] == "hold_5" for e in _leads(s)):
            exits.append(f"{s['symbol']}: the close 5 sessions after the signal.")
    cautions = list(common)
    worse = [b for b in basis if b["dev_per_drawdown"] is not None and b["dev_matched_per_drawdown"] is not None
             and b["dev_per_drawdown"] < b["dev_matched_per_drawdown"]]
    if worse:
        scaled = any(b["benchmark"] == "risk_matched" for b in worse)
        what = ("buy-and-hold scaled to the same time in the market and the same volatility while in a trade"
                if scaled else "buy-and-hold at the same time in the market")
        cautions.insert(0, f"Per unit of drawdown, {what} did better in 2010-2026 for {len(worse)} of these "
                           f"{len(basis)} rule pricings. The edge showed up mainly in the 1993-2009 period, which had "
                           "two crashes.")
    cautions.append("The registered rules have no stop loss: daily data can't show whether a stop would have filled.")
    cautions.append(f"The evidence shown is for buying at the next open after the {latest} close. The closing-price "
                    "entry has passed.")
    symbols = sorted({s["symbol"] for s in fired})
    headline = f"Long candidate: registered oversold rule fired on {' and '.join(symbols)} at the {latest} close"
    status = "registered_setup"
    if entry_passed:
        headline = f"Long setup from the {latest} close: its next-open entry has passed"
        status = "registered_setup_entry_passed"
        cautions.insert(0, "The next-open entry this evidence was tested on has passed. The evidence does not cover "
                           "a later entry.")
    return {"direction": "long", "status": status, "headline": headline,
            "reason": "Backtested evidence below (ETF pricing, bought at the next open, after costs). A Lead is a "
                      "rule worth watching forward, not proof of an edge; the verdict's definition is under "
                      "the registered signals.",
            "basis": basis, "cautions": cautions, "exit": exits, "changes": [], "close_only": close_only,
            "short_note": SHORT_NOTE}


def verdict_caution(export_info: dict) -> str | None:
    """The caution a long call carries about what the backtester's Lead means (v2 and later), or None (v1)."""
    version = (export_info or {}).get("verdict_version")
    if version not in ("v2", "v3"):
        return None
    window = ""
    if version == "v3":
        end = export_info.get("development_end") or "2026-11-13"
        window = (f" The backtester's development window is fixed to end {end}; trades signalled after it are its "
                  "forward record, and a Lead that falls below its band there stops being a Lead.")
    return (f"These are Lead {version} verdicts, and provisional: the 1993-2009 period also helped choose these "
            "signals, so it is not independent confirmation. Only trades after 2026-11-08 are untouched evidence; "
            f"the stance log and paper book below are that record.{window}")


def build_state(root: Path, now: pd.Timestamp) -> dict:
    root = Path(root)
    etfs = data.etfs(root, now)
    vix = data.cboe(root, "VIX", now)
    reg = regime.build(root, now, etfs)
    payload, export_info = signals.load_export()
    sig = signals.build(etfs, payload)["signals"]
    cards = evidence_cards.load(export_info)  # the backtester's evidence.json; "unavailable" never blocks the page
    evidence_cards.attach(sig, cards)
    earn = earnings.build(root, now, etfs)
    latest = f"{etfs['SPY'].index[-1]:%Y-%m-%d}" if "SPY" in etfs else None
    check = eligibility.evidence_check(export_info, sig, latest)
    entry_at = None
    if latest:
        from refresh_guard import entry_time
        entry_at = entry_time(pd.Timestamp(latest))
    view = morning.build(root, now)
    call = stance(sig, reg, earn, latest, check, entry_passed=bool(entry_at is not None and now >= entry_at))
    if call["direction"] == "long" and view["futures"].get("status") == "ok" and view["mode"] in ("morning", "evening"):
        moves = "; ".join(f"{r.get('name') or r['symbol']} {r['change_since_4pm']:+.2%}" for r in view["futures"]["rows"]
                          if r.get("change_since_4pm") is not None)
        if moves:
            call["cautions"].append(f"Since the 4 PM close ({view['futures']['snapshot_et']} ET snapshot): {moves}. "
                                    "A move up before the open has already taken part of any bounce; the evidence "
                                    "is not split by gap size yet.")
    provisional = verdict_caution(export_info)
    if call["direction"] == "long" and provisional:
        call["cautions"].append(provisional)
    moved = movers.build(root, now, latest)
    if moved.get("flagged") and moved.get("current"):
        call["cautions"].append(f"Large move in a top index holding on {moved['session']}: "
                                + "; ".join(f"{r['name']} {r['move']:+.1%}" for r in moved["flagged"])
                                + ". A single-stock shock can drive an index signal; it is not part of any registered rule.")
    try:
        stance_rows = calls.read(root, stance_log.LOG)
    except ValueError:
        stance_rows = []
    try:
        import intraday_hourly
        fresh = view["futures"].get("rows") if view["futures"].get("status") == "ok" and view["mode"] == "morning" else None
        hourly = intraday_hourly.build(root, now, fresh)
    except Exception as exc:  # research context only: never blocks the page
        hourly = {"status": "unavailable", "reason": str(exc)[:200], "symbols": []}
    try:
        import zero_dte
        same_day = zero_dte.summary(root, etfs)
    except Exception as exc:  # research data only: never blocks the page
        same_day = {"status": "unavailable", "reason": str(exc)[:200], "rows": [], "latest": []}
    return {"schema_version": SCHEMA, "as_of": now.isoformat(), "latest_close": latest,
            "view": view, "stance": call,
            "paper_book": paper_book.build(root, now, etfs, sig, stance_rows),
            "preclose": preclose.summary(root, etfs, sig), "same_day_options": same_day,
            "news": news.build(root, now, latest), "movers": moved,
            "earnings_calendar": earnings_calendar.build(root, now), "releases": releases.build(root, now),
            "first_release": alfred.build(root, now), "hourly_base_rates": hourly, "macro": macro.build(root, now),
            "next_entry_et": entry_at.isoformat() if entry_at is not None else None,
            "regime": reg, "signals": sig, "evidence_source": export_info, "evidence_check": check,
            "evidence_cards": evidence_cards.meta(cards), "archive": archive.summary(root),
            "ops": ops.build(root, now, latest, check),
            "risk": risk.build(root, etfs, vix, reg["volatility"].get("implied_daily_move"), now),
            "earnings": earn, "calls": calls.summary(root, etfs), "stance_log": stance_log.summary(root, etfs, sig),
            "journal": journal.summary(root, etfs), "ideas": ledger.summary(root),
            "sources": {
                "prices": "Yahoo Finance daily bars (dividend-adjusted), checked against FRED's index closes on the Data quality tab",
                "volatility": "Cboe VIX and VIX3M daily closes",
                "credit": "FRED: Moody's Baa-10y (since 1986), ICE BofA high-yield and CCC spreads (last 3 years)",
                "rates": "FRED Treasury yields (DGS10, DGS2)",
                "events": "The app's CPI, jobs and Fed calendar",
                "earnings": "Yahoo Finance and Nasdaq.com (Zacks) earnings dates",
                "evidence": "Trading Backtester trade-simulation export (ETF pricing only)",
                "overnight": "Scheduled market snapshots: CME E-mini futures via Yahoo; Cleveland Fed inflation nowcast"}}


def render(root: Path, out: Path, state: dict | None = None) -> Path:
    from stage1.report import hub_nav
    from today.build import embedded_json, json_safe
    from validation import now_et, write_component_manifest

    root, out = Path(root), Path(out)
    state = json_safe(state if state is not None else build_state(root, now_et()))
    page = TEMPLATE.read_text(encoding="utf-8")
    page = re.sub(r"\{\{(HUB_NAV|STATE)\}\}", lambda m: {"HUB_NAV": hub_nav("thesis"), "STATE": embedded_json(state)}[m.group(1)], page)
    out.mkdir(parents=True, exist_ok=True)
    (out / "thesis.html").write_text(page, encoding="utf-8")
    render_macro(out, state, page)
    (out / "thesis_state.json").write_text(json.dumps(state, indent=1, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    write_component_manifest("thesis", out, {"state_schema_version": SCHEMA, "latest_close": state.get("latest_close"),
                                             "evidence_sha256": (state.get("evidence_source") or {}).get("sha256"),
                                             "readonly_render": True})
    return out / "thesis.html"


def render_macro(out: Path, state: dict, thesis_page: str) -> Path:
    """The Macro tab (macro.html): releases, rates, conditions and gauges, from the same build as the thesis."""
    from stage1.report import hub_nav
    from today.build import embedded_json
    style = re.search(r"<style>.*?</style>", thesis_page, re.S)
    regime = state.get("regime") or {}
    small = {"as_of": state.get("as_of"), "latest_close": state.get("latest_close"), "macro": state.get("macro"),
             "releases": state.get("releases"), "first_release": state.get("first_release"),
             "credit": regime.get("credit"), "rates": regime.get("rates")}
    page = MACRO_TEMPLATE.read_text(encoding="utf-8")
    page = re.sub(r"\{\{(STYLE|HUB_NAV|STATE)\}\}", lambda m: {"STYLE": style.group(0) if style else "",
                                                             "HUB_NAV": hub_nav("macro"),
                                                             "STATE": embedded_json(small)}[m.group(1)], page)
    (out / "macro.html").write_text(page, encoding="utf-8")
    return out / "macro.html"


def refresh_sources(root: Path, say=print) -> None:
    """Online builds only: download credit spreads and earnings dates (each failure keeps the saved copy)."""
    from . import credit
    for name, job in (("credit spreads", credit.refresh), ("earnings dates", earnings.refresh),
                      ("earnings calendar", earnings_calendar.refresh), ("large-holding prices", movers.refresh),
                      ("release values", releases.refresh), ("first-release values", alfred.refresh),
                      ("FRED rates and conditions", macro.refresh)):
        try:
            result = job(root)
            say(f"Thesis sources: {name}: {result}")
        except Exception as exc:  # a failed download never blocks the build
            say(f"Thesis sources: {name} failed: {exc}")


def log_stance(root: Path, state: dict, now: pd.Timestamp, say=print) -> dict:
    """Online builds only: append the page's stance for the latest close, then refresh its summary in `state`."""
    try:
        result = stance_log.append_daily(root, state, now)
    except Exception as exc:  # a logging failure never blocks the page
        result = {"logged": 0, "skipped": f"error: {exc}"}
    say(f"Thesis stance log: {result}")
    try:  # the day's key values, kept because thesis_state.json is replaced at every build
        kept = archive.append_daily(root, state, now)
    except Exception as exc:  # never blocks the page
        kept = {"logged": 0, "skipped": f"error: {exc}"}
    say(f"Daily archive: {kept}")
    state["archive"] = {**archive.summary(root), "last_attempt": kept}
    state["stance_log"] = stance_log.summary(root, data.etfs(root, now), state.get("signals"))
    state["stance_log"]["last_attempt"] = result
    try:  # the ticket must include a stance logged in this same build
        etfs = data.etfs(root, now)
        state["paper_book"] = paper_book.build(root, now, etfs, state.get("signals") or [], calls.read(root, stance_log.LOG))
    except ValueError:
        pass
    state["ops"] =ops.build(root, now, state.get("latest_close"), state.get("evidence_check"))
    return result


def offline_requested() -> bool:
    return os.environ.get("APP_OFFLINE") == "1" or os.environ.get("APP_REPLAY") == "1"


def recording_requested() -> bool:
    """Online builds append the stance, except a data-only refresh (APP_NO_RECORD=1), which downloads only."""
    return not offline_requested() and os.environ.get("APP_NO_RECORD") != "1"
