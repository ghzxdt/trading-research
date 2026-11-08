"""Data checks shown in the report: what looked wrong in the free data, and what was done about it.

Each check is one row with a level:
  ok    nothing to worry about
  note  something odd was found and handled; worth knowing, doesn't change the findings much
  warn  something could make this report wrong or out of date; also shown at the top of the report
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .dataset import LEVERAGED, REMOVED, UNCONFIRMED
from .sources import ETFS
from validation import freshness


def _day(ts) -> str:
    ts = pd.Timestamp(ts)
    return f"{ts:%b} {ts.day}, {ts.year}"


def _when(dt) -> str:
    if dt is None:
        return "unknown time"
    return f"{_day(dt)} at {dt:%I:%M %p}".replace(" 0", " ")


def _dates(idx) -> str:
    return ", ".join(_day(d) for d in idx)


def check(raw: dict, table: pd.DataFrame, status: dict | None = None, long: pd.DataFrame | None = None) -> dict:
    status = status or {}
    items: list[dict] = []
    banner: list[str] = []
    last = table.index[-1]

    def add(level: str, name: str, result: str, action: str):
        items.append({"level": level, "check": name, "result": result, "action": action})
        if level == "warn":
            banner.append(f"{name}: {result} {action}")

    # --- How each source was loaded --------------------------------------------------------------
    failed = [s for s, i in status.items() if i["how"] == "failed"]
    offline = [s for s, i in status.items() if i["how"] == "offline"]
    for s in failed:
        add("warn", f"{s} download", f"Failed, so this report uses the copy saved {_when(status[s]['saved'])}.",
            "Re-run later for fresh data.")
    if offline:
        saved = min(status[s]["saved"] for s in offline if status[s]["saved"]) if any(status[s]["saved"] for s in offline) else None
        add("note", "Offline run", f"Built from saved copies (oldest saved {_when(saved)}).", "Run without --offline for fresh data.")
    if status and not failed and not offline:
        add("ok", "Downloads", "All three sources downloaded fresh on this run.", "")

    # --- Does every source reach the newest trading day? ----------------------------------------
    for tk in ETFS:
        col = f"{tk.lower()}_close"
        f = freshness(table[col].last_valid_index() if col in table else None)
        add("ok" if f["ok"] else "warn", f"{tk} freshness", f["reason"],
            "Historical charts remain available; stale data must not enable a current call." if not f["ok"] else "")
    for col in ("vix", "vix9d", "vix3m", "vvix"):
        f = freshness(raw["vol"][col].last_valid_index())
        add("ok" if f["ok"] else "warn", f"{col.upper()} freshness", f["reason"], "Cboe may post after the equity close.")
    for col in ("dgs2", "dgs10"):
        f = freshness(raw["rates"][col].last_valid_index(), kind="rates")
        add("ok" if f["ok"] else "warn", f"{col.upper()} freshness", f["reason"], "One equity-session publication allowance; bond holidays can cause additional lag.")

    # --- Dates and price sanity ------------------------------------------------------------------
    if table.index.is_unique and table.index.is_monotonic_increasing:
        add("ok", "Dates", f"{len(table):,} trading days, no duplicates, in order.", "")
    else:
        add("warn", "Dates", "Duplicate or out-of-order dates found.", "Delete data/raw/etfs.csv and re-run.")

    outside = {}
    for tk in ETFS:
        k = tk.lower()
        if f"{k}_high" not in table:
            continue
        hi, lo = table[f"{k}_high"] * 1.0005, table[f"{k}_low"] * 0.9995
        bad = ((table[f"{k}_open"] > hi) | (table[f"{k}_open"] < lo) | (table[f"{k}_close"] > hi) | (table[f"{k}_close"] < lo)).sum()
        if bad:
            outside[tk] = int(bad)
    if outside:
        add("note", "Open or close outside the day's high-low range",
            ", ".join(f"{k} {v}" for k, v in outside.items()) + " days.", "Kept, but these prices are suspect.")
    else:
        add("ok", "Open or close outside the day's high-low range", "None.", "")

    # --- Opening prices that equal yesterday's close --------------------------------------------
    counts = {tk: int((table[f"{tk.lower()}_flag"] == UNCONFIRMED).sum()) for tk in ETFS if f"{tk.lower()}_flag" in table}
    spy_years = pd.Series(table.index[table["spy_flag"] == UNCONFIRMED].year).value_counts()
    busy = sorted(int(y) for y, n in spy_years.items() if n >= 5)
    where = f" Most of SPY's are in {', '.join(map(str, busy))}." if busy else ""
    add("note", "Opening price exactly equals yesterday's close",
        ", ".join(f"{k} {v}" for k, v in counts.items()) + " days." + where,
        "Left out of the overnight/daytime split. It can be a real flat open or a price the data provider filled in; daily data can't tell which.")

    # --- Bad prices removed, and real tracking misses kept -------------------------------------
    removed = {tk: table.index[table[f"{tk.lower()}_flag"] == REMOVED] for tk in ETFS if f"{tk.lower()}_flag" in table}
    removed = {k: v for k, v in removed.items() if len(v)}
    if removed:
        add("note", "Bad prices removed", "; ".join(f"{k} {_dates(v)}" for k, v in removed.items()) + ".",
            "A 3x fund moved far from 3x one day and just as far back the next: one bad closing price. That day's prices were blanked.")
    else:
        add("ok", "Bad prices removed", "None found.", "")

    misses = []
    for lev, und, mult in LEVERAGED:
        if f"{lev.lower()}_ret" not in table:
            continue
        gap = (table[f"{lev.lower()}_ret"] - mult * table[f"{und.lower()}_ret"]).abs()
        misses += [(d, lev) for d in table.index[gap > 0.03]]
    if misses:
        days = sorted({d for d, _ in misses})
        add("note", "3x funds more than 3 points off 3x in a day", f"{len(misses)} fund-days, on {_dates(days)}.",
            "Kept: these were real crash or rally days, when a fund's daily reset can't keep up.")
    else:
        add("ok", "3x funds more than 3 points off 3x in a day", "None.", "")

    # --- Zero volume ----------------------------------------------------------------------------
    zero = {}
    for tk in ETFS:
        col = f"{tk.lower()}_volume"
        if col in table:
            d = table.index[(table[col] == 0) & table[f"{tk.lower()}_close"].notna()]
            if len(d):
                zero[tk] = d
    if zero:
        add("note", "Days with zero shares traded",
            "; ".join(f"{k} {len(v)} ({_day(v[0])} to {_day(v[-1])})" for k, v in zero.items()) + ".",
            "Prices on those days look normal, and no study uses volume.")
    else:
        add("ok", "Days with zero shares traded", "None.", "")

    # --- Gaps in the fear gauges and yields ------------------------------------------------------
    gaps = []
    for col, name in [("vix", "VIX"), ("vix9d", "VIX9D"), ("vix3m", "VIX3M"), ("vvix", "VVIX")]:
        n = int(table[col].isna().sum())
        if n:
            first = table[col].first_valid_index()
            gaps.append(f"{name} {n} days" + (f" (starts {_day(first)})" if first is not None and first > table.index[0] else ""))
    if gaps:
        add("note", "Missing fear-gauge values", "; ".join(gaps) + ".", "Those days are skipped in tests that need them.")
    else:
        add("ok", "Missing fear-gauge values", "None.", "")
    n_y = int(table["yield_2y_known"].isna().sum())
    add("ok" if n_y == 0 else "note", "Missing Treasury yields", f"{n_y} days." if n_y else "None.",
        "" if n_y == 0 else "Yields aren't used in any study yet.")

    # --- Long history (risk numbers only) ------------------------------------------------------
    if long is not None and len(long):
        spy0 = long["spy_close"].first_valid_index()
        qqq0 = long["qqq_close"].first_valid_index() if "qqq_close" in long else None
        old = long.loc[:"2009-12-31"]
        n_unc = int((old["spy_flag"] == UNCONFIRMED).sum()) if len(old) else 0
        add("note" if n_unc else "ok", "Long history (risk study)",
            f"SPY from {_day(spy0)}" + (f", QQQ from {_day(qqq0)}" if qqq0 is not None else "") + f"; {n_unc} SPY opens before 2010 exactly equal the prior close.",
            "Those are left out of the gap numbers. Older Yahoo opening prices are the least reliable part of the data.")

    # --- Event calendar ------------------------------------------------------------------------
    ev = raw["events"]
    nxt, past_gap = {}, {}
    for name, label in [("jobs_report", "jobs"), ("cpi", "CPI"), ("fed_decision", "Fed")]:
        dates = pd.DatetimeIndex(ev.loc[ev["event"] == name, "date"]).sort_values()
        future = dates[dates > last]
        nxt[label] = future[0] if len(future) else None
        past = dates[dates <= last]
        past_gap[label] = (last - past[-1]).days if len(past) else None
    upcoming = ", ".join(f"{k} {_day(v)}" for k, v in nxt.items() if v is not None)
    missing = [k for k in ("jobs", "CPI", "Fed") if nxt[k] is None]
    stale = [k for k in ("jobs", "CPI") if past_gap[k] is not None and past_gap[k] > 40]
    stale += ["Fed"] if past_gap["Fed"] is not None and past_gap["Fed"] > 90 else []
    if missing or stale:
        why = []
        if missing:
            why.append(f"No upcoming {' or '.join(missing)} dates in the file.")
        if stale:
            why.append(f"The latest past {' and '.join(stale)} date is over 40 days old, so recent ones may be missing.")
        add("warn", "Event calendar", " ".join(why) + (f" Next known: {upcoming}." if upcoming else ""),
            "Add dates from the BLS release schedule to data/events/events.csv (see README).")
    else:
        add("ok", "Event calendar", f"Next in the file: {upcoming}.", "")

    summary = {lvl: sum(1 for i in items if i["level"] == lvl) for lvl in ("ok", "note", "warn")}
    return {"items": items, "banner": banner, "summary": summary}
