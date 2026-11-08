"""Assemble and render the Daily thesis tab (thesis.html, thesis_state.json). Read-only: never collects data.

The stance rules are fixed here (2026-11-08) and only use registered evidence:
- Long candidate: a registered oversold rule fired at the latest close on SPY or QQQ, and the backtester rated
  at least one ETF pricing of it a Lead (random-entry test in both periods plus beating exposure-matched
  buy-and-hold). Every caution that applies is listed with it.
- Flat: nothing registered fired. The page then lists the closes that would fire each Lead rule.
- Short: never suggested. No short rule has evidence (the rally shorts failed the 1993-2009 holdout).
The user makes the actual call and records it in the call log.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pandas as pd

from . import calls, data, earnings, morning, regime, risk, signals

TEMPLATE = Path(__file__).with_name("template.html")
SCHEMA = 1


def _sessions_after(start: pd.Timestamp, count: int) -> list[pd.Timestamp]:
    """The next `count` weekdays after `start` (an approximation of sessions: holidays aren't excluded)."""
    return list(pd.bdate_range(start + pd.Timedelta(days=1), periods=count))


def _leads(signal: dict) -> list[dict]:
    return [e for e in signal["evidence"] if e["verdict"] == "Lead"]


def stance(sig: list[dict], reg: dict, earn: dict, latest: str | None) -> dict:
    fired = [s for s in sig if s["fired"] and _leads(s)]
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
    if not fired:
        changes = []
        for s in sig:
            if _leads(s) and s["trigger_close"]:
                changes.append({"symbol": s["symbol"], "rule": s["label"], "close_at_or_below": s["trigger_close"],
                                "distance": s["trigger_close"] / s["close"] - 1})
        return {"direction": "flat", "status": "no_registered_setup",
                "headline": f"Flat: no registered setup at the {latest} close",
                "reason": "None of the backtester's Lead rules fired. Regime and events below are context only.",
                "basis": [], "cautions": common, "exit": [], "changes": changes,
                "short_note": "Short is never suggested: no registered short rule has evidence."}
    basis, exits = [], []
    for s in fired:
        for e in _leads(s):
            dev, hold = e["development"], e["holdout"] or {}
            basis.append({"symbol": s["symbol"], "rule": s["label"], "exit": e["exit_label"], "mode": e["mode_label"],
                          "dev_trades": dev["trades"], "dev_win_rate": dev.get("win_rate"), "dev_mean_net": dev.get("mean_net"),
                          "dev_random_percentile": dev.get("random_percentile"),
                          "dev_per_drawdown": dev["strategy"].get("return_per_drawdown"),
                          "dev_matched_per_drawdown": dev["matched"].get("return_per_drawdown"),
                          "dev_max_drawdown": dev["strategy"].get("max_drawdown"), "dev_avg_loss": dev.get("avg_loss"),
                          "holdout_trades": hold.get("trades"), "holdout_win_rate": hold.get("win_rate"),
                          "holdout_mean_net": hold.get("mean_net"),
                          "holdout_per_drawdown": (hold.get("strategy") or {}).get("return_per_drawdown"),
                          "holdout_matched_per_drawdown": (hold.get("matched") or {}).get("return_per_drawdown")})
        if any(e["exit"] == "close_above_sma5" for e in _leads(s)):
            exits.append(f"{s['symbol']}: the first close above its 5-day average (about ${s['sma5']:.2f} now; it moves "
                         "daily) or after 10 sessions, whichever comes first.")
        if any(e["exit"] == "hold_5" for e in _leads(s)):
            exits.append(f"{s['symbol']}: the close 5 sessions after the signal.")
    cautions = list(common)
    worse = [b for b in basis if b["dev_per_drawdown"] is not None and b["dev_matched_per_drawdown"] is not None
             and b["dev_per_drawdown"] < b["dev_matched_per_drawdown"]]
    if worse:
        cautions.insert(0, "Per unit of drawdown, buy-and-hold at the same time in the market did better in 2010-2026 "
                           f"for {len(worse)} of these {len(basis)} rule pricings. The edge showed up mainly in the "
                           "1993-2009 holdout, which had two crashes.")
    cautions.append("The registered rules have no stop loss: daily data can't show whether a stop would have filled.")
    cautions.append(f"The signal fired at the {latest} close, so the 'buy at the signal close' price has passed. "
                    "The next-open pricing is the one still available.")
    symbols = sorted({s["symbol"] for s in fired})
    return {"direction": "long", "status": "registered_setup",
            "headline": f"Long candidate: registered oversold rule fired on {' and '.join(symbols)} at the {latest} close",
            "reason": "Backtested evidence below (ETF pricing, after costs). A Lead is a rule worth watching forward, "
                      "not proof of an edge.",
            "basis": basis, "cautions": cautions, "exit": exits, "changes": [],
            "short_note": "Short is never suggested: no registered short rule has evidence."}


def build_state(root: Path, now: pd.Timestamp) -> dict:
    root = Path(root)
    etfs = data.etfs(root, now)
    vix = data.cboe(root, "VIX", now)
    reg = regime.build(root, now, etfs)
    payload, export_info = signals.load_export()
    sig = signals.build(etfs, payload)["signals"]
    earn = earnings.build(root, now, etfs)
    latest = f"{etfs['SPY'].index[-1]:%Y-%m-%d}" if "SPY" in etfs else None
    return {"schema_version": SCHEMA, "as_of": now.isoformat(), "latest_close": latest,
            "view": morning.build(root, now), "stance": stance(sig, reg, earn, latest), "regime": reg,
            "signals": sig, "evidence_source": export_info,
            "risk": risk.build(root, etfs, vix, reg["volatility"].get("implied_daily_move")),
            "earnings": earn, "calls": calls.summary(root, etfs),
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
    (out / "thesis_state.json").write_text(json.dumps(state, indent=1, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    write_component_manifest("thesis", out, {"state_schema_version": SCHEMA, "latest_close": state.get("latest_close"),
                                             "evidence_sha256": (state.get("evidence_source") or {}).get("sha256"),
                                             "readonly_render": True})
    return out / "thesis.html"


def refresh_sources(root: Path, say=print) -> None:
    """Online builds only: download credit spreads and earnings dates (each failure keeps the saved copy)."""
    from . import credit
    for name, job in (("credit spreads", credit.refresh), ("earnings dates", earnings.refresh)):
        try:
            result = job(root)
            say(f"Thesis sources: {name}: {result}")
        except Exception as exc:  # a failed download never blocks the build
            say(f"Thesis sources: {name} failed: {exc}")


def offline_requested() -> bool:
    return os.environ.get("APP_OFFLINE") == "1" or os.environ.get("APP_REPLAY") == "1"
