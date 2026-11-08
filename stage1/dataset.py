"""Build the daily table: one row per trading day, every column labeled with WHEN it was knowable.

The "known at" labels are what keep later tests honest: a test that predicts day D may only use
columns that were known before the moment it claims to act.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from .sources import ETFS

TRADING_DAYS_PER_YEAR = 252
NY = ZoneInfo("America/New_York")

# Known-at labels used in the data dictionary.
PREV_CLOSE = "previous session after Cboe volatility close (~4:15 pm), before this session"
OPEN = "this day's open (9:30 am)"
CLOSE = "this day's close (4:00 pm)"
VOL_CLOSE = "this day's close (Cboe publishes ~4:15 pm)"
NEXT_DAY = "published the next day (H.15 lag) - shifted so it lines up with the day you'd see it"
CALENDAR = "known in advance (scheduled)"


def _drop_unfinished_today(df: pd.DataFrame) -> pd.DataFrame:
    """If the newest row is today and the market hasn't closed yet, it's a partial day: drop it."""
    now = datetime.now(NY)
    if len(df) and df.index[-1].date() == now.date() and (now.hour, now.minute) < (16, 30):
        return df.iloc[:-1]
    return df


def _third_fridays(calendar: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """Monthly options expiration: the 3rd Friday, or the trading day before it if that's a holiday.

    A month only counts once the calendar has reached its 3rd Friday. Before that, the newest row
    would otherwise be picked as "the last trading day on or before the 3rd Friday" and mislabeled.
    """
    out = []
    months = pd.period_range(calendar[0], calendar[-1], freq="M")
    for m in months:
        first = m.to_timestamp()
        fridays = pd.date_range(first, first + pd.offsets.MonthEnd(0), freq="W-FRI")
        if len(fridays) < 3:
            continue
        target = fridays[2]
        if target > calendar[-1]:
            continue  # this month's expiration hasn't happened yet
        candidates = calendar[calendar <= target]
        if len(candidates) and candidates[-1].to_period("M") == m:
            out.append(candidates[-1])
    return pd.DatetimeIndex(out)


LEVERAGED = [("TQQQ", "QQQ", 3), ("SQQQ", "QQQ", -3), ("UPRO", "SPY", 3), ("SPXU", "SPY", -3)]
UNCONFIRMED = "open = prior close (unconfirmed)"
REMOVED = "bad price removed"


def _bad_closes(frames: dict[str, pd.DataFrame]) -> dict[str, pd.DatetimeIndex]:
    """Find single bad closing prices in the 3x funds.

    A 3x fund should move about 3x its index every day. One bad close shows up as a big miss one
    day and a big miss the other way the next day. Real misses on crash days are small next to the
    move itself (a 3-point miss on a 30% move), so they aren't caught.
    """
    out = {}
    for lev, und, mult in LEVERAGED:
        if lev not in frames or und not in frames:
            continue
        lc, uc = frames[lev]["close"], frames[und]["close"]
        want = mult * (uc / uc.shift(1) - 1)
        miss = (lc / lc.shift(1) - 1) - want
        big = ((miss.abs() > 0.03) & (miss.abs() > 0.5 * want.abs())).fillna(False)
        flipped = np.sign(miss) == -np.sign(miss.shift(-1))
        out[lev] = miss.index[big & big.shift(-1, fill_value=False) & flipped]
    return out


def build(raw: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Returns (daily_table, data_dictionary)."""
    etfs: dict[str, pd.DataFrame] = raw["etfs"]
    spy = _drop_unfinished_today(etfs["SPY"])
    cal = spy.index
    t = pd.DataFrame(index=cal)
    t.index.name = "date"
    dictionary: list[tuple[str, str, str]] = []

    def add(col: str, values, meaning: str, known_at: str):
        t[col] = values
        dictionary.append((col, meaning, known_at))

    # --- Prices and the three ways to slice a day ---------------------------------------------
    frames = {tk: etfs[tk].reindex(cal) for tk in ETFS if tk in etfs}
    bad = _bad_closes(frames)
    for tk, p in frames.items():
        p = p.copy()
        k = tk.lower()
        flag = pd.Series("", index=cal, dtype="object")
        if len(bad.get(tk, [])):
            p.loc[bad[tk], ["open", "high", "low", "close"]] = np.nan
            flag[bad[tk]] = REMOVED
        prev_close = p["close"].shift(1)
        # An open exactly equal to yesterday's close can be real (a flat open) or a price the data
        # provider filled in. We can't tell, so those days are left out of the overnight/daytime split.
        unconfirmed = pd.Series(np.isclose(p["open"], prev_close, rtol=1e-6, atol=0.0), index=cal)
        flag[unconfirmed & (flag == "")] = UNCONFIRMED
        add(f"{k}_open", p["open"], f"{tk} opening price (adjusted)", OPEN)
        add(f"{k}_close", p["close"], f"{tk} closing price (adjusted)", CLOSE)
        add(f"{k}_high", p["high"], f"{tk} high of the day (adjusted)", CLOSE)
        add(f"{k}_low", p["low"], f"{tk} low of the day (adjusted)", CLOSE)
        add(f"{k}_volume", p["volume"], f"{tk} shares traded", CLOSE)
        add(f"{k}_ret", p["close"] / prev_close - 1, f"{tk} full-day return, close to close", CLOSE)
        add(f"{k}_overnight", (p["open"] / prev_close - 1).mask(unconfirmed),
            f"{tk} overnight return, yesterday's close to today's open (blank if the open is unconfirmed)", OPEN)
        add(f"{k}_daytime", (p["close"] / p["open"] - 1).mask(unconfirmed),
            f"{tk} daytime return, today's open to today's close (blank if the open is unconfirmed)", CLOSE)
        add(f"{k}_range", (p["high"] - p["low"]) / prev_close, f"{tk} high-to-low swing as a share of yesterday's close", CLOSE)
        add(f"{k}_flag", flag, f"{tk} data note: blank = fine; '{UNCONFIRMED}' = overnight/daytime left blank; '{REMOVED}' = that day's prices blanked", CLOSE)

    # --- Fear gauges ---------------------------------------------------------------------------
    vol = raw["vol"].reindex(cal)
    add("vix", vol["vix"], "VIX: expected S&P 500 volatility over the next 30 days (annual %)", VOL_CLOSE)
    add("vix9d", vol["vix9d"], "VIX9D: same idea over the next 9 days", VOL_CLOSE)
    add("vix3m", vol["vix3m"], "VIX3M: same idea over the next 3 months", VOL_CLOSE)
    add("vvix", vol["vvix"], "VVIX: how jumpy VIX itself is expected to be", VOL_CLOSE)
    add("short_vs_30d_fear", t["vix9d"] / t["vix"], "VIX9D / VIX. Above 1 = near-term fear higher than 30-day fear", VOL_CLOSE)
    add("30d_vs_3m_fear", t["vix"] / t["vix3m"], "VIX / VIX3M. Above 1 = 'inverted': stress right now", VOL_CLOSE)

    # Expected one-day move for THIS day, from the VIX close the day before (the "VIX / 16" rule).
    exp_move = t["vix"].shift(1) / 100 / np.sqrt(TRADING_DAYS_PER_YEAR)
    add("expected_move", exp_move, "Expected one-day SPY move (1 std. dev.) implied by yesterday's VIX close", PREV_CLOSE)
    add("spy_move_vs_expected", t["spy_ret"] / exp_move, "Today's SPY move measured in expected moves (+1.0 = up one expected move)", CLOSE)
    add("spy_overnight_vs_expected", t["spy_overnight"] / exp_move, "Overnight gap measured in expected moves", OPEN)
    add("spy_daytime_vs_expected", t["spy_daytime"] / exp_move, "Daytime move measured in expected moves", CLOSE)
    add("spy_realized_10d", t["spy_ret"].rolling(10).std(), "Typical daily SPY move over the last 10 days (actual, not expected)", CLOSE)

    # --- Interest rates (published with a one-day lag, so shift them to when you'd see them) ----
    # FRED has a blank row on bond-market holidays (e.g. Columbus Day), so fill those before lining
    # the yields up with stock trading days.
    rates = raw["rates"].ffill(limit=3).reindex(cal, method="ffill", limit=3)
    add("yield_2y_known", rates["dgs2"].shift(1), "2-year Treasury yield, as of the latest published value", NEXT_DAY)
    add("yield_10y_known", rates["dgs10"].shift(1), "10-year Treasury yield, as of the latest published value", NEXT_DAY)

    # --- Calendar ------------------------------------------------------------------------------
    add("gap_days", pd.Series(cal, index=cal).diff().dt.days,
        "Calendar days since the previous equity trading session", CALENDAR)
    ev = raw["events"]
    for name, label in [("jobs_report", "Jobs report day (8:30 am)"), ("cpi", "Inflation (CPI) report day (8:30 am)"), ("fed_decision", "Fed decision day (usually 2:00 pm)")]:
        selected = ev["event"] == name
        if name == "fed_decision":
            # Emergency decisions cannot be used as an evening-before scheduled event signal.
            if "scheduled" in ev:
                scheduled = ev["scheduled"].astype(str).str.lower().isin(["true", "1", "yes"])
            else:
                scheduled = ~ev.get("note", pd.Series("", index=ev.index)).str.contains("unscheduled", case=False, na=False)
            selected &= scheduled
            label = "Scheduled Fed decision date (full-session studies; release times vary)"
        dates = pd.DatetimeIndex(ev.loc[selected, "date"])
        dates = dates[(dates >= cal[0]) & (dates <= cal[-1])]
        # A report released while the stock market is closed (e.g. Good Friday) hits prices on the
        # next trading day, so it counts there.
        idx = cal.searchsorted(dates)
        add(f"is_{name}", cal.isin(cal[idx]), label, CALENDAR)
    if "scheduled" in ev:
        emergency = (ev["event"] == "fed_decision") & ~ev["scheduled"].astype(str).str.lower().isin(["true", "1", "yes"])
    else:
        emergency = (ev["event"] == "fed_decision") & ev.get("note", pd.Series("", index=ev.index)).str.contains("unscheduled", case=False, na=False)
    emergency_dates = pd.DatetimeIndex(ev.loc[emergency, "date"])
    emergency_dates = emergency_dates[(emergency_dates >= cal[0]) & (emergency_dates <= cal[-1])]
    add("is_unscheduled_fed_decision", cal.isin(cal[cal.searchsorted(emergency_dates)]),
        "Emergency Fed action occurrence; not an advance event signal", "known only after the unscheduled announcement")
    add("is_monthly_opex", cal.isin(_third_fridays(cal)), "Monthly options expiration (3rd Friday)", CALENDAR)
    month = cal.to_period("M")
    last_in_month = pd.Series(month, index=cal) != pd.Series(month, index=cal).shift(-1)
    if len(cal):
        # The newest month may not be over yet, so its last row isn't necessarily month-end.
        last_in_month.iloc[-1] = cal[-1] == (cal[-1] + pd.offsets.BMonthEnd(0))
    add("is_month_end", last_in_month.values, "Last trading day of the month", CALENDAR)
    add("is_ordinary_day", ~(t["is_jobs_report"] | t["is_cpi"] | t["is_fed_decision"] | t["is_unscheduled_fed_decision"] | t["is_monthly_opex"] | t["is_month_end"]),
        "Historical comparison days without the listed scheduled or emergency events", "historical classification; emergency exclusions known after announcement")

    # --- Day type ------------------------------------------------------------------------------
    z = t["spy_move_vs_expected"]
    day_type = pd.Series(pd.NA, index=cal, dtype="object")
    day_type[z < -1] = "big drop"
    day_type[(z >= -1) & (z < -0.3)] = "normal drop"
    day_type[(z >= -0.3) & (z <= 0.3)] = "quiet"
    day_type[(z > 0.3) & (z <= 1)] = "normal rise"
    day_type[z > 1] = "big rise"
    add("spy_day_type", day_type, "Today's SPY day sorted by size vs. expected: big drop / normal drop / quiet / normal rise / big rise", CLOSE)

    # The first row has no "yesterday", so most derived columns are empty there.
    t = t.iloc[1:]
    dd = pd.DataFrame(dictionary, columns=["column", "meaning", "known_at"])
    return t, dd


def build_long(raw: dict) -> pd.DataFrame:
    """SPY (1993-) and QQQ (1999-) with the VIX, for risk numbers only: worst days, gaps, liquidation odds.

    Same column names as the main table (spy_close, spy_overnight, ...) so the same code reads both.
    Opens that exactly equal the prior close are left out of the overnight/daytime split, as in build().
    """
    long = raw["etfs_long"]
    spy = _drop_unfinished_today(long["SPY"])
    cal = spy.index
    cols = {}
    for tk, frame in long.items():
        p = frame.reindex(cal)
        k = tk.lower()
        prev = p["close"].shift(1)
        unconfirmed = pd.Series(np.isclose(p["open"], prev, rtol=1e-6, atol=0.0), index=cal)
        cols[f"{k}_open"], cols[f"{k}_high"], cols[f"{k}_low"], cols[f"{k}_close"] = p["open"], p["high"], p["low"], p["close"]
        cols[f"{k}_ret"] = p["close"] / prev - 1
        cols[f"{k}_overnight"] = (p["open"] / prev - 1).mask(unconfirmed)
        cols[f"{k}_daytime"] = (p["close"] / p["open"] - 1).mask(unconfirmed)
        cols[f"{k}_flag"] = pd.Series("", index=cal, dtype="object").mask(unconfirmed, UNCONFIRMED)
    t = pd.DataFrame(cols, index=cal)
    t.index.name = "date"
    vix = raw["vol"]["vix"].reindex(cal)
    t["vix"] = vix
    t["expected_move"] = vix.shift(1) / 100 / np.sqrt(TRADING_DAYS_PER_YEAR)
    t["spy_move_vs_expected"] = t["spy_ret"] / t["expected_move"]
    # Calendar days since the previous trading day: 1 = weeknight, 3 = normal weekend, else a holiday.
    t["gap_days"] = pd.Series(cal, index=cal).diff().dt.days
    return t.iloc[1:]
