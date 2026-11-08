"""Market regime from saved daily data: trend, volatility, credit, breadth, rates and scheduled events.

Every figure is an observation with its date. The one historical comparison ("what happened after days like
today") uses buckets declared here on 2026-11-08 before looking at results: trend (SPY above or below its
200-day average) x VIX level (below 15, 15-20, 20-30, 30 and up). It is context, not a trade signal.
"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd

from . import credit as credit_source
from . import data

TREND_SYMBOLS = ("SPY", "QQQ", "IWM")
VIX_BUCKETS = ((0.0, 15.0, "VIX below 15"), (15.0, 20.0, "VIX 15-20"), (20.0, 30.0, "VIX 20-30"),
               (30.0, math.inf, "VIX 30 and up"))
DEVELOPMENT_START = pd.Timestamp("2010-01-01")
EVENT_LABELS = {"cpi": "CPI", "jobs_report": "Jobs report", "fed_decision": "Fed decision"}


def _date(ts) -> str:
    return f"{pd.Timestamp(ts):%Y-%m-%d}"


def sma(series: pd.Series, n: int) -> pd.Series:
    return series.rolling(n, min_periods=n).mean()


def vix_bucket(value: float) -> str | None:
    if value is None or not np.isfinite(value):
        return None
    return next(label for low, high, label in VIX_BUCKETS if low <= value < high)


def percentile(history: pd.Series, value: float) -> float | None:
    history = history.dropna()
    return float((history <= value).mean()) if len(history) and np.isfinite(value) else None


def trend(frame: pd.DataFrame) -> dict:
    close = frame["close"]
    last = float(close.iloc[-1])
    s50, s200 = sma(close, 50).iloc[-1], sma(close, 200).iloc[-1]
    above50 = bool(last > s50) if np.isfinite(s50) else None
    above200 = bool(last > s200) if np.isfinite(s200) else None
    state = ("Above its 50- and 200-day averages" if above50 and above200 else
             "Below its 50- and 200-day averages" if above50 is False and above200 is False else
             "Above the 200-day, below the 50-day" if above200 else
             "Below the 200-day, above the 50-day" if above200 is False else "Not enough history")
    return {"date": _date(close.index[-1]), "close": last, "sma50": s50, "sma200": s200,
            "vs_sma50": last / s50 - 1 if np.isfinite(s50) else None,
            "vs_sma200": last / s200 - 1 if np.isfinite(s200) else None,
            "return_20d": last / float(close.iloc[-21]) - 1 if len(close) > 21 else None, "state": state}


def volatility(vix: pd.Series, vix3m: pd.Series, spy: pd.DataFrame | None) -> dict:
    if vix.empty:
        return {"status": "unavailable", "reason": "No saved Cboe VIX history."}
    last, day = float(vix.iloc[-1]), vix.index[-1]
    ten_years = vix[vix.index > day - pd.DateOffset(years=10)]
    ratio = float(last / vix3m.loc[day]) if day in vix3m.index and vix3m.loc[day] > 0 else None
    realized = None
    if spy is not None and len(spy) > 21:
        realized = float(spy["close"].pct_change().iloc[-20:].std(ddof=1) * math.sqrt(252))
    level = ("calm" if last < 15 else "normal" if last < 20 else "elevated" if last < 30 else "stressed")
    return {"status": "ok", "date": _date(day), "vix": last, "bucket": vix_bucket(last), "level": level,
            "percentile_10y": percentile(ten_years, last), "vix3m": float(vix3m.loc[day]) if day in vix3m.index else None,
            "term_ratio": ratio,
            "term_state": None if ratio is None else ("Inverted: near-term fear above 3-month (stress)" if ratio > 1
                                                      else "Normal upward slope (contango)"),
            "implied_daily_move": last / 100 / math.sqrt(252), "realized_20d": realized,
            "change_5d": float(last - vix.iloc[-6]) if len(vix) > 6 else None}


def credit_view(series: dict) -> list[dict]:
    rows = []
    for name, label in credit_source.SERIES.items():
        values = series.get(name, pd.Series(dtype=float))
        if values.empty:
            rows.append({"series": name, "label": label, "status": "unavailable",
                         "reason": "Not downloaded yet; the next online refresh fetches it from FRED."})
            continue
        last = float(values.iloc[-1])
        rows.append({"series": name, "label": label, "status": "ok", "date": _date(values.index[-1]), "value": last,
                     "change_1m": float(last - values.iloc[-22]) if len(values) > 22 else None,
                     "change_3m": float(last - values.iloc[-64]) if len(values) > 64 else None,
                     "percentile": percentile(values, last), "since": _date(values.index[0]),
                     "history_note": None if name == "BAA10Y" else "FRED provides only about 3 years of this series, "
                                                                    "so its percentile covers a short window."})
    return rows


def breadth(etfs: dict) -> dict:
    spy, rsp = etfs.get("SPY"), etfs.get("RSP")
    if spy is None or rsp is None or len(rsp) < 61:
        return {"status": "unavailable", "reason": "RSP or SPY history missing."}
    joined = pd.concat([spy["close"], rsp["close"]], axis=1, keys=["spy", "rsp"]).dropna()
    rel = {f"relative_{n}d": float(joined["rsp"].iloc[-1] / joined["rsp"].iloc[-1 - n]
                                   - joined["spy"].iloc[-1] / joined["spy"].iloc[-1 - n]) for n in (20, 60)}
    return {"status": "ok", "date": _date(joined.index[-1]), **rel,
            "reading": "Equal-weight lagging: gains concentrated in the largest stocks" if rel["relative_20d"] < -0.01 else
                       "Equal-weight leading: broad participation" if rel["relative_20d"] > 0.01 else
                       "Equal-weight and cap-weight moving together"}


def rates(root: Path, now) -> dict:
    raw = Path(root) / "data" / "raw"
    ten, two = data.fred(raw / "DGS10.csv", now), data.fred(raw / "DGS2.csv", now)
    if ten.empty or two.empty:
        return {"status": "unavailable", "reason": "Treasury yields not saved."}
    joined = pd.concat([ten, two], axis=1, keys=["ten", "two"]).dropna()
    last = joined.iloc[-1]
    return {"status": "ok", "date": _date(joined.index[-1]), "ten_year": float(last["ten"]), "two_year": float(last["two"]),
            "curve": float(last["ten"] - last["two"]),
            "ten_year_change_1m": float(last["ten"] - joined["ten"].iloc[-22]) if len(joined) > 22 else None}


def _independent(days: pd.DatetimeIndex, index: pd.DatetimeIndex, horizon: int) -> int:
    positions = index.get_indexer(days)
    count, next_free = 0, -1
    for p in positions:
        if p >= next_free:
            count, next_free = count + 1, p + horizon
    return count


def regime_history(spy: pd.DataFrame, vix: pd.Series) -> dict:
    """SPY's next 5 and 20 sessions after days in today's trend x VIX bucket, by period, against all days."""
    close = spy["close"]
    table = pd.DataFrame({"close": close, "above200": close > sma(close, 200), "vix": vix.reindex(close.index)})
    table["fwd5"], table["fwd20"] = close.shift(-5) / close - 1, close.shift(-20) / close - 1
    table = table[sma(close, 200).notna() & table["vix"].notna()]
    if table.empty:
        return {"status": "unavailable", "reason": "Not enough SPY/VIX history."}
    today = table.iloc[-1]
    bucket, above = vix_bucket(float(today["vix"])), bool(today["above200"])
    table["bucket"] = table["vix"].map(vix_bucket)
    match = (table["bucket"] == bucket) & (table["above200"] == above)
    periods = []
    for name, mask in (("2010 on", table.index >= DEVELOPMENT_START), ("1993-2009", table.index < DEVELOPMENT_START)):
        stats = {"period": name}
        for label, rows in (("similar", table[mask & match]), ("all", table[mask])):
            for h in (5, 20):
                col = rows[f"fwd{h}"].dropna()
                stats[f"{label}_days_{h}"] = int(len(col))
                stats[f"{label}_independent_{h}"] = _independent(col.index, table.index, h)
                stats[f"{label}_mean_{h}"] = float(col.mean()) if len(col) else None
                stats[f"{label}_positive_{h}"] = float((col > 0).mean()) if len(col) else None
                stats[f"{label}_p10_{h}"] = float(col.quantile(0.10)) if len(col) >= 20 else None
        periods.append(stats)
    return {"status": "ok", "date": _date(table.index[-1]),
            "condition": f"SPY {'above' if above else 'below'} its 200-day average, {bucket}",
            "periods": periods,
            "note": "Overlapping windows: consecutive days share most of their future, so the independent count "
                    "(non-overlapping windows) is the honest sample size. Buckets were fixed before looking."}


def events(root: Path, now, spy: pd.DataFrame | None, days_ahead: int = 14) -> dict:
    """Scheduled CPI, jobs and Fed days ahead, with SPY's historical move on such days versus other days."""
    path = Path(root) / "data" / "events" / "events.csv"
    if not path.exists():
        return {"status": "unavailable", "upcoming": [], "history": [], "reason": "No saved event calendar."}
    table = pd.read_csv(path, dtype=str).fillna("")
    table["day"] = pd.to_datetime(table["date"], errors="coerce")
    table = table.dropna(subset=["day"])
    today = now.tz_convert(data.NY).normalize().tz_localize(None)
    ahead = table[(table["day"] >= today) & (table["day"] <= today + pd.Timedelta(days=days_ahead))]
    upcoming = [{"date": r["date"], "time_et": r.get("time_et") or None, "event": r["event"],
                 "label": EVENT_LABELS.get(r["event"], r["event"]), "note": r.get("note") or None}
                for r in ahead.sort_values("day").to_dict("records")]
    history = []
    if spy is not None and len(spy) > 300:
        moves = spy["close"].pct_change().abs()
        moves = moves[moves.index >= DEVELOPMENT_START].dropna()
        known = table[table["day"] <= moves.index[-1]]
        any_event = moves.index.isin(pd.DatetimeIndex(known["day"]))
        normal = moves[~any_event]
        for event, label in EVENT_LABELS.items():
            days = pd.DatetimeIndex(known.loc[known["event"] == event, "day"])
            on = moves[moves.index.isin(days)]
            if len(on):
                history.append({"event": event, "label": label, "days": int(len(on)),
                                "median_move": float(on.median()), "normal_median_move": float(normal.median()),
                                "ratio": float(on.median() / normal.median()) if normal.median() > 0 else None,
                                "since": _date(on.index[0])})
    return {"status": "ok", "upcoming": upcoming, "history": history,
            "note": "Moves are SPY's absolute close-to-close change on the scheduled day since 2010 (CPI and jobs "
                    "come out at 8:30 AM ET, so their move includes the opening gap). Scheduled dates come from the "
                    "app's calendar; release values are not available yet."}


def build(root: Path, now, etfs: dict) -> dict:
    vix, vix3m = data.cboe(root, "VIX", now), data.cboe(root, "VIX3M", now)
    spy = etfs.get("SPY")
    return {"trend": {s: trend(etfs[s]) for s in TREND_SYMBOLS if s in etfs and len(etfs[s]) > 200},
            "volatility": volatility(vix, vix3m, spy),
            "credit": credit_view(credit_source.load(root, now)),
            "breadth": breadth(etfs), "rates": rates(root, now),
            "history": regime_history(spy, vix) if spy is not None else {"status": "unavailable"},
            "events": events(root, now, spy)}
