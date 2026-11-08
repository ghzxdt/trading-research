"""GEX/DIX data: your saved copy, lined up with the Indexes tab's daily table, plus the refresh indicator.

Source: SqueezeMetrics' free CSV (squeezemetrics.com/monitor/dix). Their terms bar systematically
retrieving data to build a database, so the app never downloads it. You download it in your
browser, and the Update button (or `run_gex.py --import`) copies it in from your Downloads folder.

Timing: a day's GEX/DIX is published after that day's close, so it's only treated as known before
the NEXT session. Every "known" column below is shifted one trading day for that reason.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from validation import output_dir, freshness, now_et

ROOT = Path(__file__).resolve().parent.parent
DIX_FILE = ROOT / "data" / "manual" / "DIX.csv"
OUT = output_dir(ROOT)
RANK_WINDOW = 252
RANK_MIN_PERIODS = 200
SOURCE_PAGE = "https://squeezemetrics.com/monitor/dix"


def load_dix(path: Path = DIX_FILE) -> pd.DataFrame | None:
    if not path.exists():
        return None
    df = pd.read_csv(path)
    df.columns = [str(c).strip().lower() for c in df.columns]
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"]).set_index("date").sort_index()
    keep = [c for c in ("price", "dix", "gex") if c in df.columns]
    df = df[keep].apply(pd.to_numeric, errors="coerce").dropna(subset=["dix", "gex"])
    return df[~df.index.duplicated(keep="last")]


def saved_at(path: Path = DIX_FILE) -> datetime | None:
    return datetime.fromtimestamp(path.stat().st_mtime) if path.exists() else None


def dix_rank(dix: pd.Series) -> pd.Series:
    """Compare with prior observations in a 252-session window; at least 200 needed."""
    return dix.rolling(RANK_WINDOW, min_periods=RANK_MIN_PERIODS).apply(lambda x: (x[:-1] < x[-1]).mean(), raw=True)


def joined(t: pd.DataFrame, dix: pd.DataFrame) -> pd.DataFrame:
    """The Indexes tab's daily table plus GEX/DIX as known before each session's open."""
    j = t.copy()
    d = dix.reindex(j.index)
    j["gex"] = d["gex"]  # that day's value (published after its close)
    j["dix"] = d["dix"]
    j["gex_known"] = d["gex"].shift(1)  # known before this day's open
    j["dix_known"] = d["dix"].shift(1)
    j["dix_rank_known"] = dix_rank(dix["dix"]).reindex(j.index).shift(1)
    return j


# ----------------------------------------------------------------------------------------------
# Refresh indicator: should you pull a fresh copy? Uses only what the other tabs already have.
# ----------------------------------------------------------------------------------------------

VIX_BANDS = [(0, 16, "under 16"), (16, 20, "16-20"), (20, 25, "20-25"), (25, 30, "25-30"), (30, 1000, "30 or higher")]


def _day(ts) -> str:
    ts = pd.Timestamp(ts)
    return f"{ts:%b} {ts.day}, {ts.year}"


def history_rates(t: pd.DataFrame, dix: pd.DataFrame) -> dict:
    """How often GEX was below zero at each VIX level, and how sticky it is."""
    gex = dix["gex"].reindex(t.index)
    ok = gex.notna() & t["vix"].notna()
    neg = (gex < 0)[ok]
    vix = t["vix"][ok]
    rates = {}
    for lo, hi, label in VIX_BANDS:
        m = (vix >= lo) & (vix < hi)
        rates[label] = (float(neg[m].mean()) if m.sum() else np.nan, int(m.sum()))
    prev = neg.shift(1)
    small = ((gex >= 0) & (gex < 1e9))[ok].shift(1)
    return {
        "by_vix": rates,
        "stay_neg": float(neg[prev == True].mean()),  # noqa: E712
        "small_to_neg": float(neg[small == True].mean()),  # noqa: E712
        "pos_to_neg": float(neg[prev == False].mean()),  # noqa: E712
    }


def band_of(vix: float) -> str:
    for lo, hi, label in VIX_BANDS:
        if lo <= vix < hi:
            return label
    return VIX_BANDS[-1][2]


def compute_status(t: pd.DataFrame | None, dix: pd.DataFrame | None) -> dict:
    """State: no_file / no_market_data / up_to_date / recommended / optional / not_needed, with reasons."""
    now = now_et().isoformat(timespec="seconds")
    if dix is None or dix.empty:
        return {"state": "no_file", "label": "No GEX/DIX file yet", "reasons": [
            "Download the CSV from SqueezeMetrics and click Update (or save it as data/manual/DIX.csv)."], "computed": now}
    if t is None or t.empty:
        return {"state": "no_market_data", "label": "Run the Indexes tab first", "reasons": [
            "The indicator needs the Indexes tab's daily data (run_stage1.py)."], "computed": now,
            "copy_through": f"{dix.index.max():%Y-%m-%d}"}
    last_mkt, copy_last = t.index[-1], dix.index.max()
    from validation import equity_sessions
    behind = max(0, len(equity_sessions(copy_last, last_mkt)) - 1) if copy_last < last_mkt else 0
    base = {"copy_through": f"{copy_last:%Y-%m-%d}", "market_through": f"{last_mkt:%Y-%m-%d}", "behind": behind, "computed": now}

    if copy_last > last_mkt or not np.isfinite(pd.to_numeric(t["vix"], errors="coerce").iloc[-1]):
        return {**base, "state": "invalid", "label": "Current GEX reading unavailable", "temp": "unknown",
                "reasons": ["GEX is ahead of the market snapshot or the latest VIX is invalid. Conditional risk guidance is suppressed."]}
    market_fresh, gex_fresh = freshness(last_mkt), freshness(copy_last, kind="gex")
    h = history_rates(t, dix)
    row = t.iloc[-1]
    vix = float(row["vix"])
    band = band_of(vix)
    rate, n = h["by_vix"][band]
    last_gex = float(dix["gex"].iloc[-1])
    rec, opt, calm = [], [], []
    when = _day(last_mkt)
    if vix >= 20:
        rec.append(f"VIX closed at {vix:.1f} on {when}. With VIX {band}, GEX has been below zero on {rate:.0%} of days.")
    elif vix >= 16:
        opt.append(f"VIX closed at {vix:.1f} on {when}. With VIX {band}, GEX has been below zero on only {rate:.0%} of days.")
    else:
        calm.append(f"VIX closed at {vix:.1f} on {when}. With VIX {band}, GEX has been below zero on {rate:.1%} of days.")
    if last_gex < 0:
        rec.append(f"Your last reading ({_day(copy_last)}) was below zero. It stayed below zero the next day {h['stay_neg']:.0%} of the time, so it may have flipped either way.")
    elif last_gex < 1e9:
        rec.append(f"Your last reading ({_day(copy_last)}) was close to zero (${last_gex / 1e9:.1f}B). From there it went below zero the next day {h['small_to_neg']:.0%} of the time.")
    dtype = row.get("spy_day_type")
    if isinstance(dtype, str) and dtype in ("big drop", "big rise"):
        rec.append(f"SPY had a {dtype} on {when} ({row['spy_ret'] * 100:+.1f}%). Positioning tends to shift after big days.")
    if float(row.get("30d_vs_3m_fear", 0) or 0) > 1:
        rec.append("The fear curve is inverted (VIX above VIX3M), a sign of stress right now.")
    # Temperature: how much the other tabs' data says GEX matters right now.
    temp = "hot" if rec else ("warm" if opt else "cold")
    if not market_fresh["ok"] or not gex_fresh["ok"]:
        return {**base, "state": "stale", "label": "Stale inputs: current GEX guidance suppressed", "temp": "unknown",
                "reasons": [market_fresh["reason"], gex_fresh["reason"], "Historical charts remain descriptive; refresh inputs before using a current regime."]}
    if copy_last == last_mkt:
        copy_note = f"Your copy runs through {_day(copy_last)}, the latest market day the app has, so it's up to date."
        state, label = "up_to_date", f"{temp.capitalize()}: your copy is up to date"
    else:
        copy_note = f"Your copy runs through {_day(copy_last)}; the market data runs through {when} ({behind} trading day{'s' if behind != 1 else ''} newer)."
        state, label = {"hot": ("recommended", "Hot: refresh recommended"), "warm": ("optional", "Warm: refresh optional"),
                        "cold": ("not_needed", "Cold: no need to refresh")}[temp]
    return {**base, "state": state, "temp": temp, "label": label, "reasons": rec + opt + calm + [copy_note], "vix": vix}


def write_status(t: pd.DataFrame | None = None, out: Path | None = None) -> dict:
    """Recompute the indicator and save output/gex_status.json (read by the tab badge on every page)."""
    out = output_dir(ROOT) if out is None else out
    if t is None:
        p = out / "daily_table.csv"
        t = pd.read_csv(p, parse_dates=["date"], index_col="date") if p.exists() else None
    status = compute_status(t, load_dix())
    out.mkdir(parents=True, exist_ok=True)
    (out / "gex_status.json").write_text(json.dumps(status, indent=1), encoding="utf-8")
    return status
