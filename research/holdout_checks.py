"""Untouched-history check: apply the four frozen rules to SPY 1993-2009 (never used for direction tests).
Read-only; prints results (quant review, 2026-11-07).

Run from the app folder:  .venv\\Scripts\\python -B research\\holdout_checks.py
Note: p-values for 5-session windows use overlapping signals and are optimistic.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

APP = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[1]
rng = np.random.default_rng(7)
L = pd.read_csv(APP / "output" / "long_history.csv", parse_dates=["date"]).set_index("date")
D = pd.read_csv(APP / "output" / "daily_table.csv", parse_dates=["date"]).set_index("date")


def day_type(z):
    out = pd.Series(pd.NA, index=z.index, dtype="object")
    out[z < -1] = "big drop"; out[(z >= -1) & (z < -0.3)] = "normal drop"
    out[(z >= -0.3) & (z <= 0.3)] = "quiet"; out[(z > 0.3) & (z <= 1)] = "normal rise"; out[z > 1] = "big rise"
    return out


def windows(t, h):
    o, c = t["spy_open"], t["spy_close"]
    unconf = np.isclose(o.shift(-1), c, rtol=1e-6, atol=0)  # next open == this close -> unconfirmed overnight
    on = (o.shift(-1) / c - 1).mask(unconf)
    return {"overnight": on,
            "close->close(h)": c.shift(-h) / c - 1,
            "open->close(h)": c.shift(-h) / o.shift(-1) - 1}


def p_perm(vals, pool, draws=20000):
    vals = vals.dropna().to_numpy(); pool = pool.dropna().to_numpy()
    if len(vals) < 5:
        return np.nan
    obs = vals.mean() - pool.mean()
    sims = pool[rng.integers(0, len(pool), size=(draws, len(vals)))].mean(axis=1) - pool.mean()
    return (np.sum(np.abs(sims) >= abs(obs)) + 1) / (draws + 1)


rules = [("rally_short_1", "big rise", None, -1, 1), ("rally_vix20_short_1", "big rise", 20, -1, 1),
         ("normal_drop_long_5", "normal drop", None, 1, 5), ("rally_short_5", "big rise", None, -1, 5)]


def report(t, label, vix_col="vix", prior_vix=False):
    print(f"\n--- {label}: {t.index[0].date()}..{t.index[-1].date()} ({len(t)} sessions) ---")
    dt = day_type(t["spy_move_vs_expected"])
    for rid, dtype, minvix, side, h in rules:
        m = dt.eq(dtype)
        if minvix:
            v = t[vix_col].shift(1) if prior_vix else t[vix_col]
            m &= v.ge(minvix)
        w = windows(t, h)
        parts = [f"{rid:20s} n={int(m.sum()):4d}"]
        for k, s in w.items():
            cond, base = side * s[m].mean(), side * s.mean()
            parts.append(f"{k}: {cond*100:+.3f}% vs {base*100:+.3f}% (p={p_perm(s[m], s):.3f})")
        print(" | ".join(parts))


# Data quality of early opens
L["unconf"] = np.isclose(L["spy_open"], L["spy_close"].shift(1), rtol=1e-6, atol=0)
print("share of SPY opens equal to prior close, by era:")
for a, b in [("1993", "1999"), ("2000", "2004"), ("2005", "2009"), ("2010", "2026")]:
    s = L.loc[a:b, "unconf"]
    print(f"  {a}-{b}: {s.mean():.1%} of {len(s)} sessions")

hold = L.loc[:"2009-12-31"].copy()
report(hold, "UNTOUCHED HOLDOUT (SPY 1993-2009)")
report(D, "Research sample (2010-2026)")
ex2020 = D[~((D.index >= "2020-02-15") & (D.index <= "2020-06-30"))]
report(ex2020, "Research sample excluding Feb 15-Jun 30 2020")
report(D, "Research sample, VIX filter from PRIOR day (signal fully known at 16:00)", prior_vix=True)
post = D.loc["2021-01-01":]
report(post, "2021-2026 only")
