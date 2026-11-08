"""Per-ticker numbers: the Indexes tab's studies, run for each ETF, plus order-flow stand-ins.

Everything here is descriptive (no luck tests). Running every luck test on all 9 tickers would
multiply the test count ~9x, and most of these tickers move together, so tested verdicts stay on
the Indexes tab. The "signal" for the day-after tables is SPY's day type (the market's day), so
each page shows what THIS ticker did after each kind of market day.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from stage1.studies import DAY_TYPES, clean, finding, mult, pct, rms, share, forward_return, daily_reset_return, normalized_wealth

CATEGORIES = [
    ("Index ETFs", ["SPY", "QQQ", "IWM", "DIA", "RSP"]),
    ("3x ETFs", ["TQQQ", "SQQQ", "UPRO", "SPXU"]),
]
NAMES = {
    "SPY": "SPDR S&P 500 ETF (large US companies)",
    "QQQ": "Invesco QQQ (Nasdaq-100: big tech-heavy companies)",
    "IWM": "iShares Russell 2000 (small US companies)",
    "DIA": "SPDR Dow Jones Industrial Average (30 blue chips)",
    "RSP": "Invesco S&P 500 Equal Weight (the average S&P stock)",
    "TQQQ": "ProShares UltraPro QQQ (3x QQQ, daily)",
    "SQQQ": "ProShares UltraPro Short QQQ (-3x QQQ, daily)",
    "UPRO": "ProShares UltraPro S&P 500 (3x SPY, daily)",
    "SPXU": "ProShares UltraPro Short S&P 500 (-3x SPY, daily)",
}
LEVERAGED = {"TQQQ": ("QQQ", 3), "SQQQ": ("QQQ", -3), "UPRO": ("SPY", 3), "SPXU": ("SPY", -3)}
PERPS = {"SPY": ["KXSPYPERP", "KXUS500PERP"], "QQQ": ["KXQQQPERP", "KXUSTECH100PERP"], "IWM": ["KXUS2000PERP"],
         "UPRO": ["KXUS500PERP", "KXSPYPERP"], "SPXU": ["KXUS500PERP", "KXSPYPERP"], "TQQQ": ["KXUSTECH100PERP", "KXQQQPERP"],
         "SQQQ": ["KXUSTECH100PERP", "KXQQQPERP"]}
VIX_EDGES = [0, 13, 16, 20, 25, 30, 1000]
VIX_LABELS = ["Under 13", "13-16", "16-20", "20-25", "25-30", "30+"]


def pct_dd(v: float) -> str:
    """Drawdowns near -100% (the inverse 3x funds) need more digits, or they round to -100.0%."""
    return f"{v * 100:.4f}%" if v < -0.995 else pct(v, 1)


def _day(ts) -> str:
    ts = pd.Timestamp(ts)
    return f"{ts:%b} {ts.day}, {ts.year}"


def _ret(close: pd.Series, n: int) -> float:
    return float(close.iloc[-1] / close.iloc[-1 - n] - 1) if len(close) > n else np.nan


def snapshot(t: pd.DataFrame, tk: str) -> dict:
    k = tk.lower()
    close, high, low, vol = t[f"{k}_close"], t[f"{k}_high"], t[f"{k}_low"], t[f"{k}_volume"]
    ok = close.notna()
    c = close[ok]
    r = t[f"{k}_ret"]
    prior_year_end = c[c.index.year < c.index[-1].year]
    ytd = float(c.iloc[-1] / prior_year_end.iloc[-1] - 1) if len(prior_year_end) else np.nan
    yrs = (c.index[-1] - c.index[0]).days / 365.25
    dd = c / c.cummax() - 1
    s = t["spy_ret"]
    both = pd.concat([r, s], axis=1).dropna()
    lastyr = both[both.index >= both.index[-1] - pd.Timedelta(days=365)]
    stress = both[t["vix"].shift(1).reindex(both.index) > 25]
    beta = lambda b: float(b.iloc[:, 0].cov(b.iloc[:, 1]) / b.iloc[:, 1].var()) if len(b) > 20 else np.nan
    return {
        "ticker": tk, "last": float(c.iloc[-1]), "date": c.index[-1], "start": c.index[0],
        "d1": float(r.iloc[-1]), "w1": _ret(close, 5), "m1": _ret(close, 21), "m3": _ret(close, 63), "ytd": ytd, "y1": _ret(close, 252),
        "cagr": float((c.iloc[-1] / c.iloc[0]) ** (1 / yrs) - 1) if yrs > 1 else np.nan,
        "hi52": float(high.tail(252).max()), "lo52": float(low.tail(252).min()),
        "vol20": float(r.tail(20).std() * np.sqrt(252)), "vol1y": float(r.tail(252).std() * np.sqrt(252)),
        "maxdd": float(dd.min()), "maxdd_date": dd.idxmin(), "dd_now": float(dd.iloc[-1]),
        "dollar_vol20": float((vol[ok] * c).tail(20).mean()), "up_share": float((r.dropna() > 0).mean()),
        "beta": beta(both), "beta_1y": beta(lastyr), "beta_stress": beta(stress), "corr": float(both.iloc[:, 0].corr(both.iloc[:, 1])),
    }


def overnight_split(t: pd.DataFrame, tk: str) -> dict:
    k = tk.lower()
    d = t[[f"{k}_overnight", f"{k}_daytime"]].dropna()
    lon, lday = np.log1p(d.iloc[:, 0]).sum(), np.log1p(d.iloc[:, 1]).sum()
    years = d.groupby(d.index.year).apply(lambda g: np.log1p(g.iloc[:, 0]).sum() > np.log1p(g.iloc[:, 1]).sum())
    return {"share": lon / (lon + lday) if (lon + lday) != 0 else np.nan, "night": float(d.iloc[:, 0].mean()), "day": float(d.iloc[:, 1].mean()),
            "years_won": int(years.sum()), "years": int(len(years)), "skipped": int((t[f"{k}_flag"] == "open = prior close (unconfirmed)").sum()),
            "growth_all": np.exp(np.log1p(t.loc[d.index, f"{k}_ret"]).cumsum()), "growth_buy_hold": normalized_wealth(t[f"{k}_close"]), "growth_on": np.exp(np.log1p(d.iloc[:, 0]).cumsum()),
            "growth_day": np.exp(np.log1p(d.iloc[:, 1]).cumsum()), "lon": float(np.expm1(lon)), "lday": float(np.expm1(lday))}


def after_market_days(t: pd.DataFrame, tk: str) -> tuple[list[list], list[float]]:
    """What THIS ticker did after each kind of SPY day."""
    k = tk.lower()
    nxt = t[f"{k}_ret"].shift(-1)
    on, day = t[f"{k}_overnight"].shift(-1), t[f"{k}_daytime"].shift(-1)
    c = t[f"{k}_close"]
    f5 = c.shift(-5) / c - 1
    typ = t["spy_day_type"]
    ok = typ.notna() & nxt.notna()
    rows, means = [], []
    groups = [(d.capitalize(), ok & (typ == d)) for d in DAY_TYPES] + [("Big rise, VIX 20+", ok & (typ == "big rise") & (t["vix"] >= 20)), ("Any day", ok)]
    for label, m in groups:
        rows.append([label, f"{int(m.sum()):,}", pct(nxt[m].mean(), 2), share((nxt[m] > 0).mean()), pct(on[m].mean(), 2), pct(day[m].mean(), 2),
                     pct(f5[m].mean(), 2), share((f5[m].dropna() > 0).mean())])
        means.append(float(nxt[m].mean()))
    return rows, means


def event_sizes(t: pd.DataFrame, tk: str) -> list[list]:
    k = tk.lower()
    exp = t["expected_move"]
    zo, zd, r = t[f"{k}_overnight"] / exp, t[f"{k}_daytime"] / exp, t[f"{k}_ret"]
    ok = zo.notna() & zd.notna()
    base = ok & t["is_ordinary_day"].astype(bool)
    bo, bd = rms(zo[base]), rms(zd[base])
    rows = []
    for label, col in [("Jobs report", "is_jobs_report"), ("Inflation (CPI)", "is_cpi"), ("Fed decision", "is_fed_decision"),
                       ("Options expiration", "is_monthly_opex"), ("Month-end", "is_month_end")]:
        m = ok & t[col].astype(bool)
        rows.append([label, f"{int(m.sum()):,}", mult(rms(zo[m]) / bo), mult(rms(zd[m]) / bd), pct(r[m].mean(), 2), share((r[m] > 0).mean())])
    rows.append(["Ordinary days", f"{int(base.sum()):,}", "1.00x", "1.00x", pct(r[base].mean(), 2), share((r[base] > 0).mean())])
    return rows


def risk(t: pd.DataFrame, tk: str) -> dict:
    k = tk.lower()
    prev = t[f"{k}_close"].shift(1)
    d = pd.DataFrame({"ret": t[f"{k}_ret"], "down": t[f"{k}_low"] / prev - 1, "up": t[f"{k}_high"] / prev - 1,
                      "vix_prev": t["vix"].shift(1), "gap": t[f"{k}_overnight"]}).dropna(subset=["ret", "vix_prev"])
    d["bucket"] = pd.cut(d["vix_prev"], VIX_EDGES, labels=VIX_LABELS, right=False)
    by_vix = []
    for b in VIX_LABELS:
        g = d[d["bucket"] == b]
        if len(g) < 20:
            by_vix.append([b, f"{len(g):,}", "-", "-", "-", "-", "-"])
            continue
        a = g["ret"].abs()
        by_vix.append([b, f"{len(g):,}", pct(rms(g["ret"]), 2, False), pct(a.quantile(0.95), 2, False), pct(a.quantile(0.99), 2, False),
                       pct(-g["down"].quantile(0.05), 2, False), pct(a.max(), 1, False)])
    stops = []
    for x in (0.01, 0.02, 0.03, 0.05, 0.10):
        stops.append([f"{x:.0%}", share((d["down"] <= -x).mean(), 1), share((d["up"] >= x).mean(), 1)])
    gd = pd.Series(t.index, index=t.index).diff().dt.days.reindex(d.index)
    monday = pd.Series(d.index.day_of_week == 0, index=d.index)
    gaps = []
    for label, m in [("Weeknight", gd == 1), ("Weekend (Fri to Mon)", (gd == 3) & monday), ("Holiday or long weekend", gd.notna() & (gd != 1) & ~((gd == 3) & monday))]:
        g = d.loc[m, "gap"].dropna()
        big = g.abs().idxmax() if len(g) else None
        gaps.append([label, f"{len(g):,}", pct(rms(g), 2, False), pct(g.abs().quantile(0.95), 2, False) if len(g) else "-",
                     f"{pct(g[big], 1)} ({_day(big)})" if big is not None else "-"])
    worst = d["down"].idxmin()
    return {"by_vix": by_vix, "stops": stops, "gaps": gaps, "worst": float(d.loc[worst, "down"]), "worst_date": worst,
            "p99": float(d["ret"].abs().quantile(0.99)), "p95": float(d["ret"].abs().quantile(0.95))}


def tracking(t: pd.DataFrame, tk: str) -> list[list] | None:
    if tk not in LEVERAGED:
        return None
    und, L = LEVERAGED[tk]
    lc, bc = t[f"{tk.lower()}_close"], t[f"{und.lower()}_close"]
    rows = []
    for h, label in [(1, "1 day"), (5, "1 week"), (21, "1 month"), (63, "3 months")]:
        gap = (forward_return(lc,h) - L * forward_return(bc,h)).dropna()
        reset = (forward_return(lc,h) - daily_reset_return(bc,h,L)).dropna()
        rows.append([label, pct(gap.median(), 2), share((gap < 0).mean()) + "; daily-reset residual " + pct(reset.median(),2)])
    rb = (bc.shift(-21) / bc - 1).dropna()
    rl = (lc.shift(-21) / lc - 1).reindex(rb.index)
    chop = rb.abs() < 0.02
    rows.append(["Overlapping near-flat 21-session windows (within +/-2%)", pct((rl[chop] - L * rb[chop]).mean(), 1), f"lost money in {share((rl[chop] < 0).mean())} of them"])
    return rows


def order_flow(t: pd.DataFrame, tk: str) -> dict:
    """Daily stand-ins for order flow (true trade-by-trade flow isn't free)."""
    k = tk.lower()
    o, h, l, c, v = (t[f"{k}_{x}"] for x in ("open", "high", "low", "close", "volume"))
    ok = c.notna() & v.notna()
    o, h, l, c, v = o[ok], h[ok], l[ok], c[ok], v[ok]
    rng = (h - l).replace(0, np.nan)
    clv = (((c - l) - (h - c)) / rng).fillna(0)  # +1 = closed at the high, -1 = at the low
    ad = (clv * v).cumsum()
    avg20 = v.rolling(20).mean()
    rel = float(v.iloc[-1] / avg20.iloc[-2]) if len(v) > 21 else np.nan
    up = c.diff() > 0
    last20 = v.tail(20)
    up_share = float(last20[up.reindex(last20.index)].sum() / last20.sum()) if last20.sum() else np.nan  # up days within the last 20
    # Where today's relative volume sits in history (share of past days with less).
    relhist = (v / avg20.shift(1)).dropna()
    rel_rank = float((relhist.iloc[:-1] < relhist.iloc[-1]).mean()) if len(relhist) > 50 else np.nan
    rel_place = int((relhist.iloc[:-1] > relhist.iloc[-1]).sum()) + 1 if len(relhist) > 50 else None  # 1 = heaviest ever
    ad3 = ad.tail(63)
    price3 = c.tail(63)
    ad_dir = float(ad3.iloc[-1] - ad3.iloc[0])
    pr_dir = float(price3.iloc[-1] / price3.iloc[0] - 1)
    return {"clv_today": float(clv.iloc[-1]), "clv_10": float(clv.tail(10).mean()), "rel_vol": rel, "rel_rank": rel_rank, "rel_place": rel_place, "rel_days": len(relhist),
            "up_vol_share": up_share, "ad": ad, "vol": v, "avg20": avg20, "ad_dir": ad_dir, "price_dir": pr_dir,
            "dollar_today": float(v.iloc[-1] * c.iloc[-1])}


def ticker_page_studies(tk: str, t: pd.DataFrame, lev: pd.DataFrame | None, dix: pd.DataFrame | None) -> tuple[list[dict], dict]:
    k = tk.lower()
    snap = snapshot(t, tk)
    ov = overnight_split(t, tk)
    rk = risk(t, tk)
    of = order_flow(t, tk)
    studies = []

    # 1. Snapshot
    c = t[f"{k}_close"].dropna()
    y = c.tail(252)
    studies.append({
        "id": "snapshot", "number": 1, "title": "Snapshot", "show_tables": True,
        "question": f"{NAMES[tk]}. Prices through {_day(snap['date'])} (adjusted for splits and dividends).",
        "tiles": [
            {"label": f"Close ({_day(snap['date'])})", "value": f"${snap['last']:,.2f}", "note": f"{pct(snap['d1'], 2)} on the day"},
            {"label": "This year", "value": pct(snap["ytd"], 1), "note": f"1 year: {pct(snap['y1'], 1)}"},
            {"label": "Below its peak", "value": pct_dd(snap["dd_now"]), "note": f"worst since {snap['start'].year}: {pct_dd(snap['maxdd'])}"},
        ],
        "charts": [{"id": f"{k}_price", "type": "line", "format": "dollar", "xUnit": "day",
                    "title": f"{tk} over the last 12 months", "subtitle": "Daily close, adjusted for splits and dividends.",
                    "x": [f"{d:%Y-%m-%d}" for d in y.index], "series": [{"name": tk, "values": clean(y.tolist())}]}],
        "findings": [],
        "tables": [{"title": "Key numbers", "columns": ["", "Value"], "rows": [
            ["1 day / 1 week / 1 month / 3 months", f"{pct(snap['d1'], 2)} / {pct(snap['w1'], 1)} / {pct(snap['m1'], 1)} / {pct(snap['m3'], 1)}"],
            ["Year to date / 1 year", f"{pct(snap['ytd'], 1)} / {pct(snap['y1'], 1)}"],
            [f"Yearly growth since {snap['start'].year}", pct(snap["cagr"], 1)],
            ["52-week high / low", f"${snap['hi52']:,.2f} / ${snap['lo52']:,.2f} (now {pct(snap['last'] / snap['hi52'] - 1, 1)} from the high)"],
            ["Volatility (annualized): last 20 days / last year", f"{pct(snap['vol20'], 1, False)} / {pct(snap['vol1y'], 1, False)}"],
            ["Worst drop from a peak since " + str(snap["start"].year), f"{pct_dd(snap['maxdd'])} (bottom {_day(snap['maxdd_date'])})"],
            ["Up days", share(snap["up_share"])],
            ["Average dollar volume, last 20 days", f"${snap['dollar_vol20'] / 1e9:,.2f}B" if snap["dollar_vol20"] >= 1e9 else f"${snap['dollar_vol20'] / 1e6:,.0f}M"],
            ["Moves per 1% SPY move: all / last year / VIX over 25", f"{snap['beta']:.2f} / {snap['beta_1y']:.2f} / {snap['beta_stress']:.2f}"],
            ["Moves with SPY (1 = lockstep)", f"{snap['corr']:.2f}"],
        ]}],
    })

    # 2. Order flow stand-ins
    vol3 = of["vol"].tail(63)
    avg3 = of["avg20"].reindex(vol3.index)
    ad6 = of["ad"].tail(126)
    side = "near the day's high" if of["clv_today"] > 0.5 else ("near the day's low" if of["clv_today"] < -0.5 else "in the middle of the day's range")
    rr = of["rel_rank"]
    place = of["rel_place"]
    if place == 1:
        rank_words = f"its heaviest day vs. normal since {snap['start'].year}"
    elif place is not None and place <= 50:
        suffix = "th" if 10 <= place % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(place % 10, "th")
        rank_words = f"the {place}{suffix} heaviest of {of['rel_days']:,} days since {snap['start'].year}"
    else:
        rank_words = f"heavier than on {rr:.0%} of days since {snap['start'].year}"
    div = ""
    if of["ad_dir"] > 0 and of["price_dir"] < 0:
        div = " Over the last 3 months the A/D line rose while the price fell (buying into weakness)."
    elif of["ad_dir"] < 0 and of["price_dir"] > 0:
        div = " Over the last 3 months the A/D line fell while the price rose (selling into strength)."
    of_find = [
        finding("fact", f"Latest day: volume was {of['rel_vol']:.2f}x its 20-day average ({rank_words}), and it closed {side}.",
                "Closing near the high on heavy volume is usually read as buyers in control into the close; near the low, sellers."),
        finding("fact", f"Last 20 days: {share(of['up_vol_share'])} of volume traded on up days.", "Above 50% leans toward accumulation, below toward distribution." + div),
        finding("fact", "These are daily stand-ins for order flow, not tested signals.",
                "True trade-by-trade flow (who bought vs sold, and the order book) isn't free for these ETFs; it comes with minute data in stage 2."),
    ]
    extra = []
    if tk == "SPY" and dix is not None and len(dix):
        extra.append(["Dark-pool DIX (S&P 500, from your GEX/DIX file)", f"{dix['dix'].iloc[-1] * 100:.1f}% on {_day(dix.index[-1])}"])
        extra.append(["GEX (S&P 500 dealer positioning)", f"${dix['gex'].iloc[-1] / 1e9:,.2f}B ({'below' if dix['gex'].iloc[-1] < 0 else 'above'} zero)"])
    if lev is not None and tk in PERPS:
        for tick in PERPS[tk]:
            r = lev[lev["ticker"] == tick]
            if len(r) and r.iloc[0]["status"] == "active":
                r = r.iloc[0]
                extra.append([f"Kalshi {r['name']} perp", f"spread {pct(r['spread'], 2, False)}, 24h volume ${r['volume_24h'] / 1e6:,.1f}M, open interest ${r['open_interest'] / 1e6:,.2f}M, max leverage {r['max_leverage']:.1f}x"])
    studies.append({
        "id": "flow", "number": 2, "show_tables": True, "title": "Order flow (daily stand-ins)",
        "question": "Free daily signs of buying and selling pressure: volume vs. usual, up-day volume, where it closes in its range, and the accumulation/distribution line.",
        "tiles": [
            {"label": "Volume vs. 20-day average", "value": f"{of['rel_vol']:.2f}x", "note": f"${of['dollar_today'] / 1e9:,.2f}B traded" if of["dollar_today"] >= 1e9 else f"${of['dollar_today'] / 1e6:,.0f}M traded"},
            {"label": "Close within the day's range", "value": f"{of['clv_today']:+.2f}", "note": "+1 = at the high, -1 = at the low"},
            {"label": "Volume on up days, last 20", "value": share(of["up_vol_share"]), "note": "over 50% = accumulation"},
        ],
        "charts": [
            {"id": f"{k}_vol", "type": "line", "format": "num", "xUnit": "day", "title": f"{tk} volume, last 3 months (millions of shares)",
             "subtitle": "Daily volume vs. its 20-day average.", "x": [f"{d:%Y-%m-%d}" for d in vol3.index],
             "series": [{"name": "Volume", "values": clean((vol3 / 1e6).tolist())}, {"name": "20-day average", "values": clean((avg3 / 1e6).tolist())}]},
            {"id": f"{k}_ad", "type": "line", "format": "num", "xUnit": "day", "title": f"{tk} accumulation/distribution line, last 6 months",
             "subtitle": "Running total of volume, weighted by where each day closed in its range. Rising = closes near highs on volume. Only its direction matters, not its level.",
             "x": [f"{d:%Y-%m-%d}" for d in ad6.index], "series": [{"name": "A/D line (millions)", "values": clean(((ad6 - ad6.iloc[0]) / 1e6).tolist())}]},
        ],
        "findings": of_find,
        "tables": [{"title": "Related flow readings", "columns": ["", "Latest"], "rows": extra}] if extra else [],
    })

    # 3. Overnight vs daytime
    w = pd.DatetimeIndex(ov["growth_on"].index.to_series().groupby(ov["growth_on"].index.to_period("W")).last().values)
    studies.append({
        "id": "overnight", "number": 3, "title": "Overnight vs. daytime",
        "question": "If you split every day into overnight (4:00 pm to 9:30 am) and daytime (9:30 am to 4:00 pm), which part made the money?",
        "tiles": [{"label": "Overnight share of paired log growth", "value": share(ov["share"]), "note": f"filtered dates since {snap['start'].year}"},
                  {"label": "Average night / day", "value": f"{pct(ov['night'], 3)} / {pct(ov['day'], 3)}", "note": "before costs"},
                  {"label": "Years overnight won", "value": f"{ov['years_won']} of {ov['years']}", "note": "calendar years"}],
        "charts": [{"id": f"{k}_growth", "type": "line", "log": True, "format": "dollar",
                    "title": f"{tk}: overnight/daytime decomposition on common dates", "subtitle": "Weekly points, log scale, no costs. All three curves exclude the same uncertain-open dates.",
                    "x": [f"{d:%Y-%m-%d}" for d in w],
                    "series": [{"name": "Full sessions (paired dates)", "values": clean(ov["growth_all"].reindex(w).tolist())},
                               {"name": "Overnight only", "values": clean(ov["growth_on"].reindex(w).tolist())},
                               {"name": "Daytime only", "values": clean(ov["growth_day"].reindex(w).tolist())}]}],
        "findings": [finding("fact", f"{share(ov['share'])} of {tk}'s paired-date log growth came overnight. Remaining overnight wealth: ${1+ov['lon']:.6g}; daytime wealth: ${1+ov['lday']:.6g} per $1.",
                             f"{ov['skipped']} days with an unconfirmed opening price are left out. Above 100% means daytime hours lost money on balance.")],
        "tables": [],
    })

    # Endpoint wealth is separate from the paired-session decomposition.
    bh = ov["growth_buy_hold"]
    bw = pd.DatetimeIndex(bh.index.to_series().groupby(bh.index.to_period("W")).last().values)
    studies[-1]["charts"].append({"id": f"{k}_buy_hold", "type": "line", "log": True, "format": "dollar",
        "title": f"{tk}: full-history buy-and-hold wealth", "subtitle": "Adjusted close / first valid adjusted close. Missing observations are gaps, not flat returns.",
        "x": [f"{d:%Y-%m-%d}" for d in bw], "series": [{"name": "Buy and hold (full history)", "values": clean(bh.reindex(bw).tolist())}]})

    # 4. After each kind of market day
    rows, means = after_market_days(t, tk)
    studies.append({
        "id": "after", "number": 4, "show_tables": True, "title": "After each kind of SPY day",
        "question": f"Days are sorted by how SPY moved vs. what VIX expected (as on the Indexes tab). What did {tk} do next?",
        "tiles": [], "findings": [finding("fact", "Descriptive only: these per-ticker numbers haven't been through the luck test.",
                                          "The tested versions (SPY) are on the Indexes tab, study 3.")],
        "charts": [{"id": f"{k}_after", "type": "bar", "format": "pct", "title": f"{tk}'s average next day, by the kind of SPY day before it",
                    "subtitle": "Close to close, before costs.", "categories": [r[0] for r in rows],
                    "series": [{"name": f"{tk} next day", "values": clean(means)}]}],
        "tables": [{"title": f"{tk} after each kind of SPY day", "columns": ["SPY's day", "Days", "Next day", "Up", "Next overnight", "Next daytime", "Next 5 days", "Higher after 5"], "rows": rows}],
    })

    # 5. Event days
    studies.append({
        "id": "events", "number": 5, "show_tables": True, "title": "Event days",
        "question": f"How big {tk}'s moves were on scheduled event days, vs. ordinary days (adjusted for the VIX level).",
        "tiles": [], "charts": [], "findings": [],
        "tables": [{"title": f"{tk} on event days", "columns": ["Event", "Days", "Overnight gap size", "Daytime move size", "Average day", "Up days"], "rows": event_sizes(t, tk)}],
    })

    # 6. Risk
    dd = (c / c.cummax() - 1)
    wd = pd.DatetimeIndex(dd.index.to_series().groupby(dd.index.to_period("W")).last().values)
    studies.append({
        "id": "risk", "number": 6, "show_tables": True, "title": "How far it can go against you",
        "question": f"How big {tk}'s bad days get at each VIX level, how often a stop at a given distance gets hit, and how big its gaps are.",
        "tiles": [{"label": "1-in-20 day", "value": pct(rk["p95"], 2, False), "note": "close to close, all VIX levels"},
                  {"label": "1-in-100 day", "value": pct(rk["p99"], 2, False), "note": "close to close"},
                  {"label": "Worst point in a day", "value": pct(rk["worst"], 1), "note": _day(rk["worst_date"])}],
        "charts": [{"id": f"{k}_dd", "type": "line", "format": "pct", "title": f"{tk}: how far below its previous peak", "subtitle": "Weekly. 0% = at a new high.",
                    "x": [f"{d:%Y-%m-%d}" for d in wd], "series": [{"name": "Below peak", "values": clean(dd.reindex(wd).tolist())}], "yMax": 0}],
        "findings": [],
        "tables": [
            {"title": f"{tk} move size by yesterday's VIX", "columns": ["VIX level", "Days", "Typical move", "1 in 20 above", "1 in 100 above", "Drop to low, 1 in 20", "Biggest"], "rows": rk["by_vix"]},
            {"title": "How often it traded this far past yesterday's close at some point in the day", "columns": ["Distance", "Below (long stop hit)", "Above (short stop hit)"], "rows": rk["stops"]},
            {"title": "Opening gaps", "columns": ["Gap", "Count", "Typical", "1 in 20 above", "Biggest"], "rows": rk["gaps"]},
        ],
    })

    # 7. 3x tracking
    tr = tracking(t, tk)
    if tr:
        und, L = LEVERAGED[tk]
        studies.append({
            "id": "tracking", "number": 7, "show_tables": True, "title": f"Does it really deliver {L:+d}x {und}?",
            "question": "Because it resets every day, its return over several days isn't exactly the multiple of the index's return.",
            "tiles": [], "charts": [], "findings": [],
            "tables": [{"title": f"{tk} vs. exactly {L:+d}x {und}", "columns": ["Holding period", "Typical gap from exact", "Share of periods it fell short"], "rows": tr}],
        })
    return studies, snap
