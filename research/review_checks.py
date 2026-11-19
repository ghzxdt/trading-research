"""Read-only review checks on the saved data (quant review, 2026-11-07). Writes nothing.

Run from the app folder:  .venv\\Scripts\\python -B research\\review_checks.py
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

APP = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[1]
OUT = APP / "output"
DATA = APP / "data"
rng = np.random.default_rng(20261107)

t = pd.read_csv(OUT / "daily_table.csv", parse_dates=["date"]).set_index("date")
o, c = t["spy_open"], t["spy_close"]
n = len(t)
print(f"daily table: {n} rows, {t.index[0].date()} .. {t.index[-1].date()}")

# Windows anchored on signal day D (row i)
overnight = o.shift(-1) / c - 1                      # D close -> D+1 open
def win(h):
    return {
        "orig_close_to_close": c.shift(-h) / c - 1,     # D close -> D+h close
        "corr_open_to_close": c.shift(-h) / o.shift(-1) - 1,  # D+1 open -> D+h close
    }

rules = [
    ("rally_short_1", "big rise", None, -1, 1),
    ("rally_vix20_short_1", "big rise", 20, -1, 1),
    ("normal_drop_long_5", "normal drop", None, 1, 5),
    ("rally_short_5", "big rise", None, -1, 5),
]

def perm_p(sig_vals, pool, draws=20000):
    """Two-sided permutation p of the signal mean vs random same-size draws from all days."""
    sig_vals = sig_vals.dropna().to_numpy(); pool = pool.dropna().to_numpy()
    k = len(sig_vals)
    obs = sig_vals.mean() - pool.mean()
    idx = rng.integers(0, len(pool), size=(draws, k))
    sims = pool[idx].mean(axis=1) - pool.mean()
    return (np.sum(np.abs(sims) >= abs(obs)) + 1) / (draws + 1)

print("\n=== Where does each lead's return live? (raw SPY, gross, side-adjusted, mean per signal) ===")
for rid, dtype, minvix, side, h in rules:
    m = t["spy_day_type"].eq(dtype)
    if minvix:
        m &= t["vix"].ge(minvix)
    w = win(h)
    row = {"rule": rid, "signals": int(m.sum())}
    for name, s in [("overnight D->D+1open", overnight), ("orig D close->D+h close", w["orig_close_to_close"]),
                    ("corrected D+1 open->D+h close", w["corr_open_to_close"])]:
        cond = side * s[m].mean()
        base = side * s.mean()
        row[name] = f"{cond*100:+.3f}% (all days {base*100:+.3f}%, excess {(cond-base)*100:+.3f}%, p={perm_p(s[m], s):.3f})"
    print(json.dumps(row, indent=1))

# Exposure-matched benchmark for Drop long 5 using the actual trade ledger
tr = pd.read_csv(OUT / "backtest_trades.csv")
print("\n=== Trade ledger vs. exposure-matched random entries (corrected timing) ===")
for rid, dtype, minvix, side, h in rules:
    g = tr[(tr["strategy"] == rid) & (tr["timing"] == "corrected") & (tr["costs_charged"] == True)]
    if g.empty:
        g = tr[(tr["strategy"] == rid) & (tr["timing"] == "corrected")]
    pool = side * win(h)["corr_open_to_close"].dropna()
    k = len(g)
    sims = pool.to_numpy()[rng.integers(0, len(pool), size=(20000, k))].mean(axis=1)
    gross = g["gross"].mean(); net = g["net"].mean(); cost = gross - net
    pct = (sims >= gross).mean()
    print(f"{rid:22s} trades={k:4d} gross/trade={gross*100:+.3f}% cost/trade={cost*100:.3f}% net/trade={net*100:+.3f}% | "
          f"random same-window entries: mean {sims.mean()*100:+.3f}% ; share of random portfolios >= strategy gross: {pct:.3f}")

# Buy-and-hold over the same span, and time in market
span = t.loc[pd.Timestamp(tr["entry_date"].min()):]
bh = span["spy_close"].iloc[-1] / span["spy_open"].iloc[0] - 1
g = tr[(tr["strategy"] == "normal_drop_long_5") & (tr["timing"] == "corrected")]
days_in = sum(len(t.loc[a:b]) for a, b in zip(pd.to_datetime(g["entry_date"]), pd.to_datetime(g["exit_date"])))
print(f"\nSPY buy-and-hold (adjusted, no costs) {span.index[0].date()}..{span.index[-1].date()}: {bh*100:+.1f}%")
print(f"normal_drop_long_5 sessions in market: {days_in} of {len(span)} ({days_in/len(span):.0%})")

# Year-by-year sign of excess for Drop long 5 (gross vs. unconditional same window by year)
pool5 = win(5)["corr_open_to_close"]
m5 = t["spy_day_type"].eq("normal drop")
yr = pd.DataFrame({"cond": pool5[m5], "year": t.index[m5].year}).groupby("year")["cond"].mean()
base_yr = pd.DataFrame({"all": pool5, "year": t.index.year}).groupby("year")["all"].mean()
ex = (yr - base_yr).dropna()
print("normal-drop 5d excess by year (pp):", " ".join(f"{y}:{v*100:+.2f}" for y, v in ex.items()))
print(f"years with positive excess: {(ex > 0).sum()} of {len(ex)}")

# (The Kalshi perps section was removed on 2026-11-19, when the user dropped perp tracking.)

# How much does dividend adjustment matter? SPY adjusted vs. price-only can't be split here,
# but report the annualized SPY drift as context.
yrs = (t.index[-1] - t.index[0]).days / 365.25
cagr = (c.iloc[-1] / c.iloc[0]) ** (1 / yrs) - 1
print(f"\nSPY adjusted CAGR over table: {cagr*100:.2f}%/yr")
