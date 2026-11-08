"""Turn raw perp data into (1) one comparable row per market and (2) the index-perp studies.

Platform-neutral on purpose: a second platform only needs its own downloader that produces the same
row columns (see MARKET_COLUMNS), and it shows up in the same table.

Risk display: published leverage and the initial/maintenance multiplier support only a
fixed-entry-notional approximation here. Directional maintenance, live mark prices,
margin changes, fees, funding and broker policy must be reconciled before sizing.
These proxy barrier studies are NOT certified liquidation calculations.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from stage1.studies import clean, mult, pct, share

from .kalshi import INDEX_PERPS, PLATFORM

NY = "America/New_York"
BAD_QUOTE = 1e12  # Kalshi fills "no quote" with 922337203685477.5807 (and bids with 0)

TYPE_NAMES = {"Indices": "Index", "Equities": "Stock", "Metals": "Metal", "Energy": "Energy", "Crypto": "Crypto"}
ETF_TICKERS = {"KXSPYPERP", "KXQQQPERP"}

# Columns of the market table: key, label, format (used by the page's sort/format code), help text.
MARKET_COLUMNS = [
    ("name", "Market", "text", "Kalshi's name for the market (ticker underneath)"),
    ("type", "Type", "text", "Index, ETF, stock, metal, energy or crypto"),
    ("platform", "Platform", "text", "Where it trades"),
    ("tracks", "Tracks", "text", "What the perp follows"),
    ("max_leverage", "Reference leverage", "lev", "Smaller available published side/reference leverage for the smallest quoted notional; not a recommended leverage"),
    ("max_leverage_long", "Long leverage estimate", "lev", "Published long estimate at the smallest quoted notional; size and margin requirements can change"),
    ("max_leverage_short", "Short leverage estimate", "lev", "Published short estimate at the smallest quoted notional; size and margin requirements can change"),
    ("cushion_long", "Long barrier estimate", "pct1", "Uncalibrated fixed-entry-notional barrier at the published long leverage; not a certified liquidation distance"),
    ("cushion_short", "Short barrier estimate", "pct1", "Uncalibrated fixed-entry-notional barrier at the published short leverage; not a certified liquidation distance"),
    ("funding_10k_day", "Funding per $10k a day (30-day avg)", "usd2", "Average over the last 30 days. Positive = longs pay shorts; negative = shorts pay longs"),
    ("funding_year", "Funding simple annualized", "pct1", "Trailing sample mean repeated for 365 calendar days; an extrapolation, not a forecast"),
    ("longs_paid", "Days longs paid", "share", "Share of funding payments in the last 30 days where longs paid (blank until there are 5)"),
    ("funding_payments", "Funding records available", "int", "Valid unique funding records including zero transfers, not only nonzero payments"),
    ("funding_sample", "Funding sample used", "text", "Actual valid sample supporting the trailing average; incomplete intervals suppress annualization"),
    ("spread", "Full bid-ask spread", "pct2", "Ask minus bid divided by midpoint; approximately a round-trip spread cost at unchanged quotes, before fees and impact. One side versus midpoint costs half this"),
    ("volume_24h", "24h volume", "usd_compact", "Dollar value traded in the last 24 hours"),
    ("open_interest", "Open interest", "usd_compact", "Dollar value of open positions"),
    ("hours", "Hours", "text", "Trading schedule right now"),
    ("since", "First funding record", "date", "Earliest valid funding record available; not necessarily the listing or first-trade date"),
]


def _num(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return np.nan
    return v if np.isfinite(v) and abs(v) < BAD_QUOTE else np.nan


def _et(ts_seconds) -> str:
    if ts_seconds in (None, ""):
        return ""
    t = pd.Timestamp(int(ts_seconds), unit="s", tz="UTC").tz_convert(NY)
    return f"{t:%a %b} {t.day}, {t:%I:%M %p} ET".replace(" 0", " ")


def _hours(m: dict) -> str:
    sch = m.get("schedule")
    if not sch:
        return "No scheduled close (24/7)"
    if sch.get("is_open"):
        nxt = _et(sch.get("next_close_ts"))
        return f"Open at saved snapshot; next scheduled close {nxt}" if nxt else "Open at saved snapshot"
    nxt = _et(sch.get("next_open_ts"))
    return f"Closed at saved snapshot; scheduled reopen {nxt}" if nxt else "Closed at saved snapshot"


def _tracks(m: dict) -> str:
    t = m.get("ticker", "")
    if t in INDEX_PERPS:
        return INDEX_PERPS[t]["tracks"]
    title = str(m.get("title", ""))
    cls = m.get("asset_class")
    if cls == "Equities":
        return f"{title} shares"
    if cls == "Crypto":
        return title.split(" ", 1)[-1] if title[:1].isdigit() else title
    return title


def _side_leverage(m: dict, side: str) -> float:
    """Use the smallest explicitly published notional; never invent a missing side."""
    values = m.get(f"{side}_leverage_estimates") or {}
    choices = [(float(k), _num(v)) for k, v in values.items()
               if str(k).replace(".", "", 1).isdigit()]
    choices = [(k, v) for k, v in choices if np.isfinite(v) and v > 0]
    return min(choices)[1] if choices else np.nan


def _barrier(leverage: float, multiplier: float, chosen_leverage: float | None = None) -> float:
    """Uncalibrated fixed-entry-notional approximation, not an exchange liquidation quote."""
    chosen = leverage if chosen_leverage is None else chosen_leverage
    if not all(np.isfinite(x) and x > 0 for x in (leverage, chosen, multiplier)) or multiplier <= 1:
        return np.nan
    value = 1 / chosen - 1 / (leverage * multiplier)
    return value if np.isfinite(value) and value > 0 else np.nan


def funding_stats(fund: pd.DataFrame, ticker: str, days: int = 30) -> dict:
    """Valid unique observations; schedule gaps suppress averages rather than imply zero cost."""
    if fund.empty or not {"market_ticker", "funding_time", "funding_rate"}.issubset(fund.columns):
        return {"n": 0}
    f = fund.loc[fund["market_ticker"] == ticker].copy()
    f["funding_time"] = pd.to_datetime(f["funding_time"], utc=True, errors="coerce")
    f["funding_rate"] = pd.to_numeric(f["funding_rate"], errors="coerce")
    f = f.loc[f["funding_time"].notna() & np.isfinite(f["funding_rate"])].sort_values("funding_time")
    f = f.drop_duplicates("funding_time", keep="last")
    if f.empty:
        return {"n": 0}
    recent = f.loc[f["funding_time"] > f["funding_time"].max() - pd.Timedelta(days=days)]
    gaps = f["funding_time"].diff().dt.total_seconds().dropna() / 86400
    step = float(gaps.median()) if len(gaps) else np.nan
    per_day = 1 / step if np.isfinite(step) and (abs(step - 1) <= .05 or abs(step - 1 / 3) <= .02) else np.nan
    span = (recent["funding_time"].max() - recent["funding_time"].min()).total_seconds() / 86400
    expected = round(span * per_day) + 1 if np.isfinite(per_day) else len(recent)
    coverage = min(1.0, len(recent) / expected) if expected else 0.0
    # One isolated record cannot establish a schedule; missing intervals must not reduce cost silently.
    day = float(recent["funding_rate"].mean()) * per_day if len(recent) >= 2 and coverage >= 0.95 else np.nan
    last = recent["funding_time"].max().tz_convert(NY)
    sample = f"{len(recent)} records / {span:.1f} elapsed calendar days; through {last:%Y-%m-%d %H:%M} ET"
    return {"n": int(len(f)), "n_recent": int(len(recent)), "per_day": per_day, "day": day, "year": day * 365,
            "longs_paid": float((recent["funding_rate"] > 0).mean()),
            "shorts_paid": float((recent["funding_rate"] < 0).mean()),
            "zero": float((recent["funding_rate"] == 0).mean()),
            "last": float(f["funding_rate"].iloc[-1]), "since": f["funding_time"].min(),
            "through": f["funding_time"].max(), "coverage": coverage, "sample": sample}


def market_rows(raw: dict) -> pd.DataFrame:
    fund = raw["funding"]
    mults = (raw.get("risk") or {}).get("initial_margin_multiplier", {})
    rows = []
    for m in raw["markets"]:
        t = m["ticker"]
        published = _num(m.get("leverage_estimate"))
        long_lev, short_lev = _side_leverage(m, "long"), _side_leverage(m, "short")
        available = [v for v in (published, long_lev, short_lev) if np.isfinite(v) and v > 0]
        lev = min(available) if available else np.nan
        im = _num(mults.get(t))
        long_c, short_c = _barrier(long_lev, im), _barrier(short_lev, im)
        complete = np.isfinite(long_c) and np.isfinite(short_c)
        # Legacy reference barrier is deliberately the tighter side, not a certified distance at lev.
        cushion = min(long_c, short_c) if complete else np.nan
        bid, ask = _num(m.get("bid")), _num(m.get("ask"))
        mid = (bid + ask) / 2 if np.isfinite(bid) and np.isfinite(ask) and 0 < bid <= ask else np.nan
        fs = funding_stats(fund, t) if len(fund) else {"n": 0}
        typ = "ETF" if t in ETF_TICKERS else TYPE_NAMES.get(m.get("asset_class"), m.get("asset_class") or "Other")
        rows.append({
            "platform": PLATFORM,
            "ticker": t,
            "name": INDEX_PERPS.get(t, {}).get("name", m.get("title", t)),
            "type": typ,
            "status": m.get("status"),
            "tracks": _tracks(m),
            "max_leverage": lev,
            "max_leverage_long": long_lev,
            "max_leverage_short": short_lev,
            "cushion_long": long_c,
            "cushion_short": short_c,
            "liquidation_model_status": "uncalibrated_proxy" if complete else "missing_inputs",
            "initial_margin_multiplier": im,
            "cushion_at_max": cushion,
            "funding_10k_day": fs["day"] * 10_000 if fs["n"] else np.nan,
            "funding_year": fs["year"] if fs["n"] else np.nan,
            "longs_paid": fs["longs_paid"] if fs["n"] and fs["n_recent"] >= 5 else np.nan,
            "funding_payments": fs["n"],
            "funding_sample": fs.get("sample", "unavailable"),
            "funding_shorts_paid": fs.get("shorts_paid", np.nan),
            "funding_zero": fs.get("zero", np.nan),
            "funding_coverage": fs.get("coverage", np.nan),
            "funding_recent_records": fs.get("n_recent", 0),
            "half_spread": (ask - bid) / (2 * mid) if np.isfinite(mid) else np.nan,
            "spread": (ask - bid) / mid if np.isfinite(mid) else np.nan,
            "volume_24h": _num(m.get("volume_24h_notional_value_dollars")),
            "open_interest": _num(m.get("open_interest_notional_value_dollars")),
            "hours": _hours(m),
            "since": fs["since"].tz_convert(NY).strftime("%Y-%m-%d") if fs["n"] else "",
            "price": _num(m.get("price")),
            "contract_size": _num(m.get("contract_size")),
        })
    df = pd.DataFrame(rows).sort_values("max_leverage", ascending=False, na_position="last")
    return df.reset_index(drop=True)


# ----------------------------------------------------------------------------------------------
# Index perps: price series
# ----------------------------------------------------------------------------------------------

def hourly_prices(candles: list[dict]) -> pd.Series:
    """Last trade price at the end of each hour (ET). Hours with no trades fall back to the bid/ask midpoint."""
    out = {}
    for c in candles:
        p = _num((c.get("price") or {}).get("close"))
        if not np.isfinite(p):
            b, a = _num((c.get("bid") or {}).get("close")), _num((c.get("ask") or {}).get("close"))
            p = (a + b) / 2 if np.isfinite(a) and np.isfinite(b) and b > 0 else np.nan
        out[pd.Timestamp(int(c["end_period_ts"]), unit="s", tz="UTC").tz_convert(NY)] = p
    return pd.Series(out, dtype=float).sort_index()


def daily_marks(fund: pd.DataFrame, ticker: str) -> pd.Series:
    """Kalshi's mark price at each daily funding time (4:00 pm ET for index perps), by date."""
    if fund.empty or not {"market_ticker", "funding_time", "mark_price"}.issubset(fund.columns):
        return pd.Series(dtype=float)
    f = fund[fund["market_ticker"] == ticker].copy()
    f["funding_time"] = pd.to_datetime(f["funding_time"], utc=True, errors="coerce")
    f["mark_price"] = pd.to_numeric(f["mark_price"], errors="coerce")
    f = f.loc[f["funding_time"].notna() & np.isfinite(f["mark_price"]) & (f["mark_price"] > 0)]
    f["day"] = f["funding_time"].dt.tz_convert(NY).dt.tz_localize(None).dt.normalize()
    return f.sort_values("funding_time").groupby("day")["mark_price"].last().sort_index()


# ----------------------------------------------------------------------------------------------
# Studies (same dict shape as stage 1, so the same page code draws them)
# ----------------------------------------------------------------------------------------------

def _hit_rates(t: pd.DataFrame, etf: str, cushion: float, short_cushion: float | None = None) -> dict:
    """Regular-session ETF barrier crossings; unavailable inputs remain unavailable."""
    sc = cushion if short_cushion is None else short_cushion
    valid_long = np.isfinite(cushion) and 0 < cushion < 1
    valid_short = np.isfinite(sc) and sc > 0
    k = etf.lower()
    required = [f"{k}_{field}" for field in ("close", "high", "low")]
    empty = {key: np.nan for key in ("long_1", "short_1", "long_5", "short_5", "long_1_recent", "worst_day")}
    empty.update({"available": False, "n_1": 0, "n_5": 0, "worst_date": pd.NaT, "since": pd.NaT})
    if t.empty or not all(c in t for c in required):
        return empty
    close, high, low = (pd.to_numeric(t[c], errors="coerce") for c in required)
    good = np.isfinite(close) & np.isfinite(high) & np.isfinite(low) & (close > 0) & (low > 0) & (high >= low)
    close, high, low = close.where(good), high.where(good), low.where(good)
    prev = close.shift(1)
    ok1 = prev.notna() & low.notna() & high.notna()
    fut_low = pd.concat([low.shift(-i) for i in range(1, 6)], axis=1).min(axis=1, skipna=False)
    fut_high = pd.concat([high.shift(-i) for i in range(1, 6)], axis=1).max(axis=1, skipna=False)
    ok5 = close.notna() & fut_low.notna() & fut_high.notna()
    down = (low / prev - 1)[ok1]
    recent = ok1 & (t.index >= t.index[-1] - pd.Timedelta(days=365))
    def rate(values, mask, threshold, valid, lower):
        if not valid or not mask.any():
            return np.nan
        return float(((values[mask] <= -threshold) if lower else (values[mask] >= threshold)).mean())
    return {"available": bool(valid_long and valid_short and ok1.any()), "n_1": int(ok1.sum()), "n_5": int(ok5.sum()),
            "long_1": rate(low / prev - 1, ok1, cushion, valid_long, True),
            "short_1": rate(high / prev - 1, ok1, sc, valid_short, False),
            "long_5": rate(fut_low / close - 1, ok5, cushion, valid_long, True),
            "short_5": rate(fut_high / close - 1, ok5, sc, valid_short, False),
            "long_1_recent": rate(low / prev - 1, recent, cushion, valid_long, True),
            "worst_day": float(down.min()) if len(down) else np.nan,
            "worst_date": down.idxmin() if len(down) else pd.NaT,
            "since": down.index[0] if len(down) else pd.NaT}


def study_liquidation(rows: pd.DataFrame, t: pd.DataFrame | None) -> dict:
    idx = rows[rows["ticker"].isin(INDEX_PERPS) & (rows["status"] == "active")]
    findings, table_rows, charts = [], [], []
    for _, r in idx.iterrows():
        proxy = INDEX_PERPS[r["ticker"]]["proxy"]
        if t is None or r.get("liquidation_model_status") != "uncalibrated_proxy":
            findings.append({"verdict": "fact", "label": "Unavailable", "kind": "direction",
                             "headline": f"{r['name']}: risk inputs or ETF history are unavailable; no barrier frequency or position size is inferred.", "detail": "Refresh valid data and reconcile the exchange's actual liquidation quote before trading."})
            continue
        h = _hit_rates(t, proxy, r["cushion_long"], r["cushion_short"])
        since = str(h["since"].year) if pd.notna(h["since"]) else "unavailable"
        table_rows.append([r["name"], mult(r["max_leverage_long"]), mult(r["max_leverage_short"]),
                           pct(r["cushion_long"], 2, False), pct(r["cushion_short"], 2, False), f"{proxy} since {since}",
                           str(h["n_1"]), share(h["long_1"], 1), share(h["short_1"], 1), str(h["n_5"]),
                           share(h["long_5"], 1), share(h["short_5"], 1)])
        findings.append({"verdict": "fact", "label": "Proxy study", "kind": "direction",
                         "headline": f"{r['name']}: {proxy}'s regular-session prices crossed the approximate long barrier on {share(h['long_1'], 1)} of {h['n_1']:,} sampled days.",
                         "detail": "This is an unconditional ETF barrier-hit frequency, not a measured probability that a Kalshi position will be liquidated. Overlapping five-session windows are not independent."})
    main = idx[idx["ticker"] == "KXUS500PERP"]
    if t is not None and len(main) and main.iloc[0].get("liquidation_model_status") == "uncalibrated_proxy":
        r = main.iloc[0]
        ref = r["max_leverage"]
        choices = sorted(set([v for v in (2, 3, 5, 8, 10) if v < ref] + [ref]))
        long_one, short_one, long_five, short_five = [], [], [], []
        for lv in choices:
            lc = _barrier(r["max_leverage_long"], r["initial_margin_multiplier"], lv)
            sc = _barrier(r["max_leverage_short"], r["initial_margin_multiplier"], lv)
            h = _hit_rates(t, "SPY", lc, sc)
            long_one.append(h["long_1"]); short_one.append(h["short_1"])
            long_five.append(h["long_5"]); short_five.append(h["short_5"])
        charts.append({"id": "liq_by_leverage", "type": "bar", "format": "pct", "unsigned": True,
                       "title": "SPY proxy barrier-hit frequencies under US500 leverage assumptions",
                       "subtitle": "Uncalibrated fixed-entry-notional approximation; regular-session highs/lows only. Not liquidation probabilities.",
                       "categories": [f"{v:.1f}x" for v in choices],
                       "series": [{"name": name, "values": clean(values)} for name, values in
                                  [("Long, 1 session", long_one), ("Short, 1 session", short_one),
                                   ("Long, 5 sessions", long_five), ("Short, 5 sessions", short_five)]]})
    return {"id": "liquidation", "number": 1, "title": "Proxy barriers and leverage risk",
            "question": "How often did ETF prices cross approximate barriers under explicit leverage assumptions?",
            "tiles": [], "charts": charts, "findings": findings,
            "tables": [{"title": "Uncalibrated proxy barrier estimates by side",
                        "columns": ["Perp", "Long leverage", "Short leverage", "Long barrier", "Short barrier", "Proxy history", "1-session cases",
                                    "Long hit, 1 session", "Short hit, 1 session", "5-session cases", "Long hit, 5 sessions", "Short hit, 5 sessions"],
                        "rows": table_rows}] if table_rows else [],
            "notes": "Not certified for position sizing. Barriers approximate 1/L minus maintenance on entry notional. Actual maintenance can depend on side, size and current mark; broker policy and margin changes matter. ETF regular-session extrema omit overnight perp paths, basis, fees, funding and execution slippage. A stop is not a guaranteed fill."}


def study_funding(rows: pd.DataFrame, fund: pd.DataFrame, t: pd.DataFrame | None) -> dict:
    idx = rows[rows["ticker"].isin(INDEX_PERPS) & (rows["status"] == "active")]
    table_rows, findings, series, dates = [], [], [], set()
    for _, r in idx.iterrows():
        fs = funding_stats(fund, r["ticker"], days=30)
        if not fs["n"]:
            continue
        cash = fs["year"] * r["max_leverage"]
        table_rows.append([r["name"], fs["sample"], f"{fs['coverage']:.0%}",
                           f"${fs['day'] * 10000:.2f}" if np.isfinite(fs['day']) else "Unavailable",
                           pct(fs["year"], 2), pct(cash, 1), share(fs["longs_paid"]), share(fs["shorts_paid"]), share(fs["zero"]),
                           f"${fs['last'] * 10000:.2f}"])
        findings.append({"verdict": "fact", "label": "Observed funding", "kind": "direction",
                         "headline": f"{r['name']}: in {fs['n_recent']} trailing-window records, longs paid {share(fs['longs_paid'])}, shorts paid {share(fs['shorts_paid'])}, and {share(fs['zero'])} were zero transfers.",
                         "detail": "Funding is signed from a long's perspective and charged on full notional. Annualized figures repeat the observed calendar-day average without compounding; they are not forecasts. Missing intervals or an unknown schedule suppress averages. Both trade fees and spread/impact are additional."})
        f = fund.loc[fund["market_ticker"] == r["ticker"]].copy()
        if len(f) >= 2:
            f = f.drop_duplicates("funding_time", keep="last")
            f["day"] = f["funding_time"].dt.tz_convert(NY).dt.strftime("%Y-%m-%d")
            daily = f.groupby("day")["funding_rate"].sum(min_count=1) * 10000
            series.append((r["name"], daily)); dates |= set(daily.index)
    charts = []
    if series:
        x = sorted(dates)
        values = [[float(s[d]) if d in s.index else None for d in x] for _, s in series]
        flat = [v for vs in values for v in vs if v is not None and np.isfinite(v)]
        if flat:
            charts = [{"id": "funding_daily", "type": "line", "format": "dollar", "xUnit": "day",
                       "yMin": min(0.0, min(flat)), "yMax": max(0.0, max(flat)),
                       "title": "Observed daily funding per $10,000: all available history",
                       "subtitle": "Positive: longs paid. Negative: shorts paid. Zero: no transfer. Table averages use the last 30-day window; missing dates are gaps.",
                       "x": x, "series": [{"name": n, "values": clean(v)} for (n, _), v in zip(series, values)]}]
    return {"id": "funding", "number": 2, "title": "Observed funding and sample coverage",
            "question": "What did funding cost in the stated historical sample, separate from execution costs?",
            "tiles": [], "charts": charts, "findings": findings,
            "tables": [{"title": "Trailing 30-calendar-day window, or shorter available sample",
                        "columns": ["Perp", "Actual sample", "Expected interval coverage", "Avg per $10k / calendar day", "Simple annualized / position",
                                    "Simple annualized / cash at reference leverage", "Longs paid", "Shorts paid", "Zero transfers", "Latest record / $10k"],
                        "rows": table_rows}] if table_rows else []}


def study_tracking(rows: pd.DataFrame, fund: pd.DataFrame, t: pd.DataFrame | None) -> dict:
    idx = rows[rows["ticker"].isin(INDEX_PERPS) & (rows["status"] == "active")]
    table_rows, findings = [], []
    for _, r in idx.iterrows():
        proxy = INDEX_PERPS[r["ticker"]]["proxy"]
        marks = daily_marks(fund, r["ticker"])
        if t is None or len(marks) < 2:
            findings.append({"verdict": "fact", "label": "Fact", "kind": "direction",
                             "headline": f"{r['name']}: not enough daily prices yet to compare with {proxy}.", "detail": "Needs at least two trading days."})
            continue
        etf = t[f"{proxy.lower()}_close"]
        both = pd.concat([marks.rename("perp"), etf.rename("etf")], axis=1, join="inner").dropna()
        rp, re_ = both["perp"].pct_change(), both["etf"].pct_change()
        d = pd.concat([rp, re_], axis=1).dropna()
        positions = pd.Series(t.index.get_indexer(both.index), index=both.index)
        consecutive = positions.diff().eq(1)
        skipped = int((~consecutive.iloc[1:]).sum())
        d = d.loc[consecutive.reindex(d.index).fillna(False)]
        n = len(d)
        if n < 2:
            findings.append({"verdict": "fact", "label": "Fact", "kind": "direction",
                             "headline": f"{r['name']}: only {len(both)} trading day{'s' if len(both) != 1 else ''} of prices so far; too early to measure tracking.", "detail": ""})
            continue
        corr = d.iloc[:, 0].corr(d.iloc[:, 1]) if n >= 3 else np.nan
        gap = (d.iloc[:, 0] - d.iloc[:, 1])
        table_rows.append([r["name"], proxy, f"{n}", f"{corr:.2f}" if np.isfinite(corr) else "-", pct(np.sqrt((gap ** 2).mean()), 2, False),
                           pct(gap.abs().max(), 2, False), mult(np.polyfit(d.iloc[:, 1], d.iloc[:, 0], 1)[0]) if n >= 3 else "-"])
        findings.append({
            "verdict": "fact", "label": "Fact", "kind": "direction",
            "headline": (f"{r['name']} vs {proxy}: over {n} trading days, their consecutive funding-mark session returns had correlation {corr:.2f} of the way, "
                         f"with an RMS daily return difference of {pct(np.sqrt((gap ** 2).mean()), 2, False)}." if np.isfinite(corr) else
                         f"{r['name']} vs {proxy}: {n} trading days so far; RMS daily return difference {pct(np.sqrt((gap ** 2).mean()), 2, False)}."),
            "detail": f"{skipped} nonconsecutive return interval(s) excluded. " + ("Only a few weeks of data, so treat this as a first look. " if n < 30 else "")
                      + ("US500 and US Tech 100 follow their own indexes, so small gaps vs SPY and QQQ are expected (dividends and index rules differ)."
                         if proxy != r["name"] else "The perp follows the ETF itself, so gaps should be tiny."),
        })
    return {
        "id": "tracking", "number": 3,
        "title": "Does each perp follow its index?",
        "question": "Consecutive ETF-session returns from funding-time marks, compared with ETF closes; these are descriptive tracking statistics, not executable trade returns.",
        "tiles": [], "charts": [], "findings": findings,
        "tables": [{"title": "Daily moves: perp vs. ETF", "columns": ["Perp", "ETF", "Days", "Moved together (1 = lockstep)", "RMS daily return difference", "Biggest return difference", "Perp move per 1% ETF move"],
                    "rows": table_rows}] if table_rows else [],
    }


def study_overnight(rows: pd.DataFrame, hourly: dict, t: pd.DataFrame | None) -> dict:
    """Perps trade while the stock market is closed. Does the perp's overnight move match the ETF's opening gap?"""
    idx = rows[rows["ticker"].isin(INDEX_PERPS) & (rows["status"] == "active")]
    table_rows, findings = [], []
    for _, r in idx.iterrows():
        proxy = INDEX_PERPS[r["ticker"]]["proxy"]
        p = hourly_prices(hourly.get(r["ticker"], []))
        if t is None or p.empty:
            continue
        local = p.copy()
        local.index = local.index.tz_localize(None)
        at4 = local[local.index.hour == 16]
        at9 = local[local.index.hour == 9]
        at4.index, at9.index = at4.index.normalize(), at9.index.normalize()
        days = t.index[(t.index >= local.index.min().normalize())]
        recs = []
        for i in range(1, len(days)):
            d0, d1 = days[i - 1], days[i]
            if d0 in at4.index and d1 in at9.index and np.isfinite(at4[d0]) and np.isfinite(at9[d1]):
                perp_night = at9[d1] / at4[d0] - 1
                etf_gap = t.loc[d1, f"{proxy.lower()}_overnight"]
                if np.isfinite(etf_gap):
                    recs.append((d1, perp_night, etf_gap))
        n = len(recs)
        if n == 0:
            findings.append({"verdict": "fact", "label": "Fact", "kind": "direction",
                             "headline": f"{r['name']}: no complete overnight yet (needs a 4:00 pm price, then the next morning's 9:00 am price and {proxy}'s open).", "detail": ""})
            continue
        d = pd.DataFrame(recs, columns=["date", "perp", "etf"]).set_index("date")
        corr = d["perp"].corr(d["etf"]) if n >= 3 else np.nan
        agree = (np.sign(d["perp"]) == np.sign(d["etf"])).mean()
        table_rows.append([r["name"], proxy, f"{n}", f"{corr:.2f}" if np.isfinite(corr) else "-", share(agree),
                           pct((d["perp"] - d["etf"]).abs().mean(), 2, False)])
        findings.append({
            "verdict": "fact", "label": "Fact", "kind": "direction",
            "headline": (f"{r['name']}: on {n} nights, its move from 4:00 pm to 9:00 am pointed the same way as {proxy}'s opening gap {share(agree)} of the time"
                         + (f" (moved together {corr:.2f} of the way)." if np.isfinite(corr) else ".")),
            "detail": ("Too few nights to judge yet; this fills in as data builds up. " if n < 30 else "")
                      + "This matters because most of SPY's gains since 2010 came overnight (Indexes tab). A perp is one of the few ways to trade those hours. "
                        "The perp uses the last trade in the hour ending 9:00 am (or midpoint if absent), half an hour before the ETF opens. The shared return interval explains much of the agreement; it is not a post-9:00 am strategy test.",
        })
    return {
        "id": "overnight_perps", "number": 4,
        "title": "Trading while the stock market is closed",
        "question": "How closely did already-realized overnight moves agree? This is not a forward prediction test.",
        "tiles": [], "charts": [], "findings": findings,
        "tables": [{"title": "Perp overnight move (4:00 pm to 9:00 am) vs. ETF opening gap", "columns": ["Perp", "ETF", "Nights", "Moved together", "Same direction", "Typical difference"],
                    "rows": table_rows}] if table_rows else [],
    }


def health(raw: dict, rows: pd.DataFrame) -> dict:
    items, banner = [], []

    def add(level, name, result, action=""):
        items.append({"level": level, "check": name, "result": result, "action": action})
        if level == "warn":
            banner.append(f"{name}: {result} {action}".strip())

    for src, info in raw["status"].items():
        stamp = pd.Timestamp(info["saved"])
        stamp = stamp.tz_localize("UTC") if stamp.tzinfo is None else stamp
        stamp = stamp.tz_convert(NY)
        when = f"{stamp:%b} {stamp.day}, {stamp:%I:%M %p} ET".replace(" 0", " ")
        if info["how"] == "failed":
            add("warn", f"{src} download", f"Failed, so this page uses the copy saved {when}.", "Re-run later.")
        elif info["how"] == "offline":
            add("note", "Offline run", f"Built from the copy saved {when}.", "Run without --offline for fresh data.")
        else:
            add("ok", "Download", f"Downloaded from Kalshi's public API at {when}.")
    act = rows[rows["status"] == "active"]
    inactive = rows[rows["status"] != "active"]
    add("ok", "Markets", f"{len(rows)} listed, {len(act)} active." + (f" Inactive: {', '.join(inactive['name'])}." if len(inactive) else ""),
        "Inactive markets are hidden unless you untick 'Active only'.")
    no_fund = act[act["funding_payments"] == 0]
    add("ok" if no_fund.empty else "note", "Funding history", "Every active market has at least one valid funding record (possibly zero)." if no_fund.empty
        else f"No valid funding record yet: {', '.join(no_fund['name'])}.", "" if no_fund.empty else "Brand-new markets; fills in after the next funding time.")
    young = act[act["funding_payments"] < 5]
    add("note" if len(young) else "ok", "New markets", f"{len(young)} active markets have fewer than 5 funding records."
        if len(young) else "All active markets have at least 5 funding records.", "Their funding averages are first looks, not settled numbers.")
    bad = 0
    for candles in raw["hourly"].values():
        for c in candles:
            for side in ("bid", "ask"):
                for k, v in (c.get(side) or {}).items():
                    try:
                        if float(v) > BAD_QUOTE or (side == "bid" and float(v) == 0):
                            bad += 1
                    except (TypeError, ValueError):
                        pass
    add("note" if bad else "ok", "Placeholder quotes in the hourly data", f"{bad} bid/ask values were Kalshi's 'no quote' placeholders." if bad else "None.",
        "Ignored. Prices use the last trade, or the bid/ask midpoint when an hour had no trades.")
    no_trade = sum(1 for cs in raw["hourly"].values() for c in cs if (c.get("price") or {}).get("close") in (None, ""))
    add("note" if no_trade else "ok", "Hours with no trades (index perps)", f"{no_trade} hours." if no_trade else "None.", "Bid/ask midpoint used instead.")
    snaps = raw.get("snapshots")
    n_snap = int(snaps["snapshot_utc"].nunique()) if snaps is not None and len(snaps) else 0
    add("note", "Saved snapshots", f"{n_snap} snapshot{'s' if n_snap != 1 else ''} of the market list saved so far.",
        "Kalshi doesn't serve past spreads or open interest, so each run saves one. Run daily to build that history.")
    missing = rows[rows["status"].eq("active") & rows["liquidation_model_status"].eq("missing_inputs")]
    add("warn" if len(missing) else "note", "Risk inputs", f"{len(missing)} active market(s) have missing side or margin inputs." if len(missing) else "Published side estimates and margin multipliers are available.", "Unavailable inputs suppress proxy frequencies; never infer zero risk.")
    add("warn", "Liquidation model not calibrated", "Published leverage and margin multipliers do not certify this app's fixed-entry-notional barrier approximation.",
        "No automatic sizing from these figures. Reconcile actual broker liquidation quotes by product, side and size, including current marks, funding and fees.")
    summary = {lvl: sum(1 for i in items if i["level"] == lvl) for lvl in ("ok", "note", "warn")}
    return {"items": items, "banner": banner, "summary": summary}
