"""Self-check: `python run_stage1.py --check` (add --offline to skip the download).

1. No look-ahead. Rebuild the daily table from data cut off at several past dates. Every row up
   to the cut must come out the same as in the full table. A column that changes was using
   information from after that day.
2. Arithmetic. Overnight and daytime returns multiply back to the full-day return.
3. Labels. Day types match their thresholds, and every column has a "known at" label.

Allowed difference: the newest row of a cut can differ in two things that need tomorrow to be
certain (both say so in the data dictionary): whether it's the last trading day of the month,
and whether a 3x fund's price was bad (a bad price is only provable the next day).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from . import dataset
from .sources import ETFS

LAST_ROW_EXCEPTIONS = {"is_month_end", "is_ordinary_day"}
CLEANED_TICKERS = {lev.lower() for lev, _, _ in dataset.LEVERAGED}


def _same(a: pd.Series, b: pd.Series) -> pd.Series:
    """Row-by-row equality that treats two blanks as equal and allows float rounding."""
    if pd.api.types.is_numeric_dtype(a) and pd.api.types.is_numeric_dtype(b) and not pd.api.types.is_bool_dtype(a):
        x, y = a.astype(float).to_numpy(), b.astype(float).to_numpy()
        return pd.Series(np.isclose(x, y, rtol=1e-9, atol=1e-12, equal_nan=True), index=a.index)
    return (a.astype(str) == b.astype(str)) | (a.isna() & b.isna())


def _cut(raw: dict, when: pd.Timestamp) -> dict:
    return {
        "etfs": {tk: df.loc[:when] for tk, df in raw["etfs"].items()},
        "etfs_long": {tk: df.loc[:when] for tk, df in raw.get("etfs_long", {}).items()},
        "vol": raw["vol"].loc[:when],
        "rates": raw["rates"].loc[:when],
        "events": raw["events"],
    }


def run(raw: dict, table: pd.DataFrame) -> list[tuple[bool, str]]:
    out: list[tuple[bool, str]] = []
    long = dataset.build_long(raw) if raw.get("etfs_long") else None

    # 1. No look-ahead -----------------------------------------------------------------------------
    idx = table.index
    # Spread across the history, plus recent days. Mid-month cuts matter: they're where an
    # "expiration day" label could be guessed too early.
    picks = [len(idx) // 5, 2 * len(idx) // 5, 3 * len(idx) // 5, 4 * len(idx) // 5, len(idx) - 25, len(idx) - 2]
    cuts = sorted({idx[i] for i in picks})
    problems = []
    for when in cuts:
        part, _ = dataset.build(_cut(raw, when))
        full = table.loc[part.index]
        for col in part.columns:
            ok = _same(part[col], full[col])
            body_bad = ~ok.iloc[:-1]
            if body_bad.any():
                first = part.index[:-1][body_bad.to_numpy()][0]
                problems.append(f"{col} changed on {first:%Y-%m-%d} when data was cut at {when:%Y-%m-%d}")
            if not ok.iloc[-1]:
                allowed = col in LAST_ROW_EXCEPTIONS or col.split("_")[0] in CLEANED_TICKERS
                if not allowed:
                    problems.append(f"{col} on the newest row differs when data was cut at {when:%Y-%m-%d}")
        if raw.get("etfs_long"):
            part_l = dataset.build_long(_cut(raw, when))
            full_l = long.loc[part_l.index]
            for col in part_l.columns:
                ok = _same(part_l[col], full_l[col])
                if (~ok).any():
                    first = part_l.index[(~ok).to_numpy()][0]
                    problems.append(f"long history {col} changed on {first:%Y-%m-%d} when data was cut at {when:%Y-%m-%d}")
    cut_list = ", ".join(f"{c:%Y-%m-%d}" for c in cuts)
    if problems:
        out.append((False, f"Look-ahead: {len(problems)} problem(s) across cuts at {cut_list}:\n      " + "\n      ".join(problems[:15])))
    else:
        out.append((True, f"No look-ahead: rebuilding with data cut at {cut_list} gives the same rows."))

    # 2. Arithmetic --------------------------------------------------------------------------------
    worst, where = 0.0, ""
    for tk in ETFS:
        k = tk.lower()
        if f"{k}_ret" not in table:
            continue
        d = table[[f"{k}_overnight", f"{k}_daytime", f"{k}_ret"]].dropna()
        err = ((1 + d[f"{k}_overnight"]) * (1 + d[f"{k}_daytime"]) - (1 + d[f"{k}_ret"])).abs()
        if len(err) and err.max() > worst:
            worst, where = float(err.max()), f"{tk} on {err.idxmax():%Y-%m-%d}"
    out.append((worst < 1e-9, f"Overnight x daytime = full day for every ETF (largest gap {worst:.1e}{', ' + where if worst >= 1e-9 else ''})."))

    # 3. Labels ------------------------------------------------------------------------------------
    z = table["spy_move_vs_expected"]
    expect = pd.Series(pd.NA, index=table.index, dtype="object")
    expect[z < -1] = "big drop"
    expect[(z >= -1) & (z < -0.3)] = "normal drop"
    expect[(z >= -0.3) & (z <= 0.3)] = "quiet"
    expect[(z > 0.3) & (z <= 1)] = "normal rise"
    expect[z > 1] = "big rise"
    mismatched = int((~_same(expect, table["spy_day_type"])).sum())
    out.append((mismatched == 0, f"Day types match their thresholds ({mismatched} mismatches)."))

    _, dictionary = dataset.build(_cut(raw, table.index[-1]))
    unlabeled = sorted(set(table.columns) - set(dictionary.loc[dictionary["known_at"].astype(str).str.len() > 0, "column"]))
    out.append((not unlabeled, "Every column has a 'known at' label." if not unlabeled else f"Columns without a 'known at' label: {', '.join(unlabeled)}"))

    opex_months = table.index[table["is_monthly_opex"]].to_period("M")
    out.append((opex_months.is_unique and table.loc[table["is_monthly_opex"]].index.max() <= table.index[-1],
                f"One options-expiration day per month ({len(opex_months)} months, none repeated)."))
    return out
