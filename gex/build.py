"""The GEX / DIX tab's content: today's reading (synced with the other tabs), recent history, the
historical tests, and a data check. Same study-dict shape as the other tabs, so the same page code draws it."""

from __future__ import annotations

import numpy as np
import pandas as pd

from stage1.studies import VERDICTS, Judge, clean, finding, mult, pct, period_table, rms, share

from .data import _day, dix_rank
from validation import freshness

def _rank_words(r: float) -> str:
    if not np.isfinite(r):
        return "not yet ranked (needs 200 sessions)"
    if r <= 0:
        return "its lowest in the trailing window"
    if r >= 1:
        return "its highest in the trailing window"
    return f"higher than {r:.0%} of prior observations in the trailing window"


PROXY = {"KXUS500PERP": "spy", "KXSPYPERP": "spy", "KXUSTECH100PERP": "qqq", "KXQQQPERP": "qqq"}


def _conditional_risk_rows(j: pd.DataFrame, lev: pd.DataFrame, negative: bool, exp: float) -> list:
    """Per-proxy, per-side adverse session excursions; never infer hits from endpoint returns."""
    rows = []
    if not np.isfinite(exp) or exp <= 0 or "gex_known" not in j or "expected_move" not in j:
        return rows
    state = (j["gex_known"] < 0) if negative else (j["gex_known"] >= 0)
    for _, r in lev.loc[lev["ticker"].isin(PROXY) & lev["status"].eq("active")].iterrows():
        px = PROXY[r["ticker"]]
        needed = [f"{px}_{c}" for c in ("open", "high", "low", "daytime")]
        if not all(c in j for c in needed) or r.get("liquidation_model_status") != "uncalibrated_proxy":
            continue
        op, high, low, day = (pd.to_numeric(j[c], errors="coerce") for c in needed)
        expected = pd.to_numeric(j["expected_move"], errors="coerce")
        valid = (state & j["gex_known"].notna() & np.isfinite(op) & (op > 0) & np.isfinite(high) &
                 np.isfinite(low) & (low > 0) & (high >= low) & np.isfinite(day) & np.isfinite(expected) & (expected > 0))
        if not valid.any():
            continue
        typical = rms((day / expected)[valid]) * exp
        for side, adverse in (("Long", (1 - low / op).clip(lower=0)), ("Short", (high / op - 1).clip(lower=0))):
            c = r.get(f"cushion_{side.lower()}", np.nan)
            leverage = r.get(f"max_leverage_{side.lower()}", np.nan)
            if not np.isfinite(c) or c <= 0 or not np.isfinite(leverage):
                continue
            standardized = (adverse / expected)[valid]
            hit = float((standardized >= c / exp).mean())
            rows.append([r["name"], side, px.upper(), mult(leverage), pct(c, 2, False),
                         f"{c / typical:.1f}" if np.isfinite(typical) and typical > 0 else "Unavailable",
                         str(int(valid.sum())), share(hit, 1)])
    return rows


def study_reading(j: pd.DataFrame, dix: pd.DataFrame, lev: pd.DataFrame | None) -> dict:
    """Suppress current conditional estimates unless both snapshots are current and aligned."""
    last_copy, last_mkt = dix.index.max(), j.index[-1]
    g, d = float(dix["gex"].iloc[-1]), float(dix["dix"].iloc[-1])
    rank_now = float(dix_rank(dix["dix"]).iloc[-1])
    vix = float(j["vix"].iloc[-1])
    exp = vix / 100 / np.sqrt(252) if np.isfinite(vix) and vix > 0 else np.nan
    usable = (last_copy == last_mkt and np.isfinite(g) and np.isfinite(exp) and
              freshness(last_mkt)["ok"] and freshness(last_copy, kind="gex")["ok"])
    findings = [finding("fact", f"Latest saved GEX ({_day(last_copy)}): ${g / 1e9:,.2f}B. DIX {d * 100:.1f}%, {_rank_words(rank_now)}.",
                        "GEX/DIX is published after the close. DIX ranks compare with prior observations in a 252-session window, with at least 200 sessions required.")]
    tiles = [{"label": f"Saved GEX ({_day(last_copy)})", "value": f"${g / 1e9:,.2f}B", "note": "Historical saved observation"},
             {"label": "DIX trailing-window rank", "value": f"{rank_now:.0%}" if np.isfinite(rank_now) else "Unavailable", "note": "252-session window; minimum 200"}]
    rows = []
    if not usable:
        findings.append(finding("fact", "Current conditional risk estimates are unavailable: the GEX and market snapshots must be fresh and cover the same session.",
                                f"Market through {_day(last_mkt)}; GEX through {_day(last_copy)}. Saved observations and historical studies remain visible; no current sizing guidance is inferred."))
    else:
        negative = g < 0
        valid = (j["spy_daytime_vs_expected"].notna() & j["gex_known"].notna())
        state = (j["gex_known"] < 0) if negative else (j["gex_known"] >= 0)
        typ = rms(j.loc[valid & state, "spy_daytime_vs_expected"]) * exp
        typical_all = rms(j.loc[valid, "spy_daytime_vs_expected"]) * exp
        findings.append(finding("fact", f"At VIX {vix:.1f}, the historical SPY session RMS for this GEX sign scales to {pct(typ, 2, False)}, versus {pct(typical_all, 2, False)} across all saved regimes.",
                                "This simple historical rescaling is not a calibrated forecast or evidence that GEX independently adds information beyond VIX. The current VIX scale is applied to each proxy's own historical distribution."))
        tiles.append({"label": "SPY historical session RMS at current VIX", "value": pct(typ, 2, False), "note": "Conditional descriptive rescaling, not a forecast"})
        if lev is not None and len(lev):
            rows = _conditional_risk_rows(j, lev, negative, exp)
    return {"id": "reading", "number": 1, "title": "Saved positioning and conditional proxy risk", "current_usable": bool(usable),
            "question": "What do fresh, aligned positioning inputs imply about historical proxy excursions under explicitly uncalibrated barriers?",
            "tiles": tiles, "charts": [], "findings": findings,
            "tables": [{"title": "Adverse regular-session excursions by proxy and side, rescaled to current VIX",
                        "columns": ["Perp", "Side", "ETF proxy", "Published side leverage", "Approximate barrier", "Barrier / proxy RMS", "Historical cases", "Adverse excursion exceeded barrier"],
                        "rows": rows}] if rows else [],
            "notes": "Not liquidation probabilities or position-size recommendations. Uses open-to-low for longs and open-to-high for shorts, each proxy's own distribution and valid sample. Overnight paths, mark/basis differences, fees, funding and changing margin are omitted."}


def study_recent(dix: pd.DataFrame, days: int = 126) -> dict:
    r = dix.tail(days)
    x = [f"{d:%Y-%m-%d}" for d in r.index]
    g = (r["gex"] / 1e9).tolist()
    charts = [{
        "id": "gex_recent", "type": "line", "format": "num", "xUnit": "day", "yMin": min(0.0, min(g)), "yMax": max(0.0, max(g)),
        "title": "GEX over the last 6 months ($ billions)",
        "subtitle": "Below zero: dealers likely add to moves. Above zero: they likely dampen them.",
        "x": x, "series": [{"name": "GEX ($B)", "values": clean(g)}],
    }]
    if "price" in r:
        charts.append({
            "id": "spx_recent", "type": "line", "format": "num", "xUnit": "day",
            "title": "S&P 500 over the same 6 months", "subtitle": "Index level, from the same SqueezeMetrics file.",
            "x": x, "series": [{"name": "S&P 500", "values": clean(r["price"].tolist())}],
        })
    neg = int((r["gex"] < 0).sum())
    return {"id": "recent", "number": 2, "title": "The last 6 months",
            "question": "Where GEX has been lately, next to the market.",
            "tiles": [], "charts": charts,
            "findings": [finding("fact", f"GEX was below zero on {neg} of the last {len(r)} trading days.", "")],
            "tables": []}


def study_history(j: pd.DataFrame, judge: Judge) -> dict:
    """Do GEX and DIX add anything beyond VIX? (Moved here from the Indexes tab.)"""
    gex, rank = j["gex_known"], j["dix_rank_known"]
    zday, day = j["spy_daytime_vs_expected"], j["spy_daytime"]
    ok = gex.notna() & zday.notna()
    neg, pos = ok & (gex < 0), ok & (gex >= 0)
    vix_prev = j["vix"].shift(1)
    res_g = judge.test(neg, zday.where(ok), pool=pos, stat="size", pool_name="days with GEX above 0")
    raw_ratio = rms(day[neg]) / rms(day[pos])
    adj_ratio = rms(zday[neg]) / rms(zday[pos])

    fwd5 = j["spy_close"].shift(-4) / j["spy_open"] - 1  # this morning's open to the close 4 days later
    z5 = fwd5 / (vix_prev / 100 / np.sqrt(252) * np.sqrt(5))
    ok5 = rank.notna() & z5.notna()
    hi, lo = ok5 & (rank > 0.8), ok5 & (rank < 0.2)
    mid = ok5 & ~hi & ~lo
    res_hi = judge.test(hi, z5.where(ok5), method="shift", pool_name="shifted")
    res_lo = judge.test(lo, z5.where(ok5), method="shift", pool_name="shifted")
    all5 = fwd5[ok5].mean()

    findings = [
        finding(res_g["verdict"],
                f"When GEX was below zero ({int(neg.sum()):,} days), the next day session moved {mult(raw_ratio)} the usual size, and {mult(adj_ratio)} after adjusting for VIX.",
                f"GEX below zero mostly happens when fear is already high (average VIX {vix_prev[neg].mean():.1f} vs {vix_prev[pos].mean():.1f} otherwise), "
                "dividing by VIX does not by itself establish incremental predictive value. Further regime-matched, out-of-sample tests are needed. Day session only, because GEX comes out after the close.", res_g),
        finding(res_hi["verdict"],
                f"When DIX was in the top 20% of its past year ({int(hi.sum()):,} days), SPY's next 5 sessions averaged {pct(fwd5[hi].mean(), 2)}, "
                f"higher {share((fwd5[hi] > 0).mean())} of the time, vs {pct(all5, 2)} and {share((fwd5[ok5] > 0).mean())} for any 5 sessions.",
                "Measured from the next morning's open.", res_hi),
        finding(res_lo["verdict"],
                f"When DIX was in the bottom 20% of its past year ({int(lo.sum()):,} days), the next 5 sessions averaged {pct(fwd5[lo].mean(), 2)}, "
                f"higher {share((fwd5[lo] > 0).mean())} of the time.", "", res_lo),
        finding("fact", "SqueezeMetrics doesn't publish how it calculates GEX or DIX, so these numbers can't be checked independently.", ""),
    ]
    chart = {"id": "dix_5d", "type": "bar", "format": "pct",
             "title": "SPY's next 5 sessions, by where DIX stood vs. its past year",
             "subtitle": "From the next morning's open, before costs. DIX history starts May 2011; ranks start after 200 sessions in a trailing 252-session window.",
             "categories": ["DIX bottom 20%", "Middle 60%", "DIX top 20%", "Any day"],
             "series": [{"name": "Average next-5-session return", "values": clean([fwd5[lo].mean(), fwd5[mid].mean(), fwd5[hi].mean(), all5])}]}
    return {"id": "history", "number": 3, "title": "Does GEX or DIX add anything beyond VIX? (history since 2011)",
            "question": "The same luck test the Indexes tab uses: is the next session bigger when GEX is below zero, and does DIX point the next week up or down?",
            "tiles": [], "charts": [chart], "findings": findings,
            "tables": [
                {"title": "GEX and the size of the next day session (SPY)",
                 "columns": ["Previous evening's GEX", "Days", "Average VIX (prior close)", "Day-session move size", "Size, VIX-adjusted", "Average day-session return", "Size verdict"],
                 "rows": [["Below 0", f"{int(neg.sum()):,}", f"{vix_prev[neg].mean():.1f}", pct(rms(day[neg]), 2, False), mult(adj_ratio), pct(day[neg].mean(), 2), VERDICTS[res_g["verdict"]]],
                          ["0 or above", f"{int(pos.sum()):,}", f"{vix_prev[pos].mean():.1f}", pct(rms(day[pos]), 2, False), "1.00x", pct(day[pos].mean(), 2), ""]]},
                {"title": "DIX and the next 5 sessions (SPY, from the open)",
                 "columns": ["Previous evening's DIX vs. its past year", "Days", "Next-5-session average", "Higher after 5 sessions", "Verdict"],
                 "rows": [["Top 20%", f"{int(hi.sum()):,}", pct(fwd5[hi].mean(), 2), share((fwd5[hi] > 0).mean()), VERDICTS[res_hi["verdict"]]],
                          ["Middle 60%", f"{int(mid.sum()):,}", pct(fwd5[mid].mean(), 2), share((fwd5[mid] > 0).mean()), ""],
                          ["Bottom 20%", f"{int(lo.sum()):,}", pct(fwd5[lo].mean(), 2), share((fwd5[lo] > 0).mean()), VERDICTS[res_lo["verdict"]]]]},
                period_table([("GEX below 0, day-session size", res_g)], title="GEX size effect by period"),
                period_table([("DIX top 20%, next 5 sessions", res_hi), ("DIX bottom 20%, next 5 sessions", res_lo)], title="DIX by period (in expected moves)"),
            ]}


def health(dix: pd.DataFrame | None, saved, t: pd.DataFrame | None, lev_saved, status: dict) -> dict:
    items = []

    def add(level, name, result, action=""):
        items.append({"level": level, "check": name, "result": result, "action": action})

    if dix is None:
        add("note", "Your GEX/DIX copy", "Not found.", "Use the buttons at the top, or save the CSV as data/manual/DIX.csv.")
    else:
        gaps = int((dix.index.to_series().diff().dt.days > 5).sum())
        when = f"{saved:%b} {saved.day}, {saved:%I:%M %p}".replace(" 0", " ") if saved else "unknown"
        add("ok", "Your GEX/DIX copy", f"{len(dix):,} days, {_day(dix.index.min())} to {_day(dix.index.max())}; saved {when}.",
            "Downloaded by hand from SqueezeMetrics; the app never fetches it (their terms bar automated retrieval).")
        add("ok" if gaps == 0 else "note", "Gaps in the file", "None over 5 days." if gaps == 0 else f"{gaps} gaps over 5 days.", "")
    if t is None:
        add("note", "Indexes tab data", "Not found.", "Run run_stage1.py (or run_all.py) so the reading has today's VIX.")
    else:
        add("ok", "Indexes tab data", f"Through {_day(t.index[-1])} (VIX, expected move, day types).", "Read-only: this tab never changes the Indexes tab.")
    add("ok" if lev_saved else "note", "Leverage tab data", f"Saved {lev_saved:%b} {lev_saved.day}, {lev_saved:%I:%M %p}".replace(" 0", " ") + "." if lev_saved else "Not found.",
        "Used for the liquidation-cushion comparison." if lev_saved else "Run run_leverage.py for the perps comparison.")
    add({"up_to_date": "ok", "not_needed": "ok", "optional": "note", "recommended": "note", "stale": "warn", "invalid": "warn"}.get(status.get("state"), "note"),
        "Refresh indicator", status.get("label", ""), " ".join(status.get("reasons", [])[:1]))
    summary = {lvl: sum(1 for i in items if i["level"] == lvl) for lvl in ("ok", "note", "warn")}
    return {"items": items, "banner": [], "summary": summary}
