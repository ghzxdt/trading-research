"""Frozen, nonoverlapping ETF-proxy experiments. No broker execution or fitted model.

Original timing uses signal-close -> exit-close. Corrected timing waits for next
session's open; a one-session hold therefore measures open -> close. Historical
perp quotes/fees are unavailable: costs are explicit scenarios, never actual fills.
"""
from __future__ import annotations

import hashlib
import json
from datetime import time
from pathlib import Path

import numpy as np
import pandas as pd

STRATEGIES = [
    {"id": "rally_short_1", "name": "Big rise: short, next session", "day_type": "big rise", "side": -1, "horizon": 1},
    {"id": "rally_vix20_short_1", "name": "Big rise + VIX >=20: short, next session", "day_type": "big rise", "min_vix": 20, "side": -1, "horizon": 1},
    {"id": "normal_drop_long_5", "name": "Normal drop: long, five sessions", "day_type": "normal drop", "side": 1, "horizon": 5},
    {"id": "rally_short_5", "name": "Big rise: short, five sessions", "day_type": "big rise", "side": -1, "horizon": 5},
]
DEFAULT_COSTS = {"initial_equity": 10000.0, "notional_fraction": 1.0,
                 "half_spread_bps": 1.0, "slippage_bps_per_side": 2.0,
                 "fee_bps_per_side": 2.0, "funding_bps_per_calendar_day": 1.36,
                 "description": "Illustrative ETF-proxy execution scenario; not verified historical Kalshi costs. Positive funding means longs pay, shorts receive."}


def validate_costs(config):
    c = {**DEFAULT_COSTS, **config}
    for key in ("initial_equity", "notional_fraction", "half_spread_bps", "slippage_bps_per_side", "fee_bps_per_side", "funding_bps_per_calendar_day"):
        c[key] = float(c[key])
        if not np.isfinite(c[key]):
            raise ValueError(f"Nonfinite {key}")
    if c["initial_equity"] <= 0 or not 0 < c["notional_fraction"] <= 1:
        raise ValueError("Research notional fraction must be >0 and <=1; no leveraged sizing is authorized by this model")
    if min(c[k] for k in ("half_spread_bps", "slippage_bps_per_side", "fee_bps_per_side")) < 0:
        raise ValueError("Execution costs cannot be negative")
    return c


def config_hash(c):
    return hashlib.sha256(json.dumps(c, sort_keys=True).encode()).hexdigest()[:16]


def signal_mask(t, rule):
    m = t["spy_day_type"].eq(rule["day_type"])
    if "min_vix" in rule:
        m &= t["vix"].ge(rule["min_vix"])
    return m.fillna(False)


def timestamp(day, hour, minute=0):
    return pd.Timestamp.combine(pd.Timestamp(day).date(), time(hour, minute)).tz_localize("America/New_York")


def trade_result(entry, exit_price, side, start, end, c):
    """Per-entry-notional return. Spread/slippage are in fills, not charged twice."""
    if min(entry, exit_price) <= 0 or not np.isfinite(entry + exit_price):
        raise ValueError("Invalid price endpoint")
    friction = (c["half_spread_bps"] + c["slippage_bps_per_side"]) / 10000
    entry_fill = entry * (1 + side * friction)
    exit_fill = exit_price * (1 - side * friction)
    price_net = side * (exit_fill - entry_fill) / entry_fill
    fee = c["fee_bps_per_side"] / 10000 * (1 + exit_fill / entry_fill)
    days = max(0.0, (end - start).total_seconds() / 86400)
    funding = side * c["funding_bps_per_calendar_day"] / 10000 * days
    gross = side * (exit_price / entry - 1)
    return {"gross": gross, "net": price_net - fee - funding, "fee": fee,
            "funding": funding, "execution_drag": gross - price_net,
            "calendar_days": days, "entry_fill": entry_fill, "exit_fill": exit_fill}


def simulate(t, rule, costs, timing="corrected", charge_costs=True):
    c = validate_costs(costs)
    mask = signal_mask(t, rule)
    equity = c["initial_equity"]
    curve = pd.Series(equity, index=t.index, dtype=float)
    trades = []
    available_after = -1
    for i in np.flatnonzero(mask.to_numpy()):
        if i < available_after:
            continue
        a, b = (i + 1 if timing == "corrected" else i), i + rule["horizon"]
        if b >= len(t):
            continue  # incomplete outcome is never treated as a loss or zero
        entry = float(t["spy_open" if timing == "corrected" else "spy_close"].iloc[a])
        exit_price = float(t["spy_close"].iloc[b])
        if not np.isfinite(entry + exit_price) or min(entry, exit_price) <= 0:
            continue
        start = timestamp(t.index[a], 9, 30) if timing == "corrected" else timestamp(t.index[a], 16)
        end = timestamp(t.index[b], 16)
        result = trade_result(entry, exit_price, rule["side"], start, end, c)
        capital = equity
        exposure = capital * c["notional_fraction"]
        for k in range(a, b + 1):
            mark = float(t["spy_close"].iloc[k])
            if not np.isfinite(mark):
                curve.iloc[k] = np.nan
                continue
            at = trade_result(entry, mark, rule["side"], start, timestamp(t.index[k],16), c)
            # Exit charges are reserved at each daily mark for conservative marked equity.
            curve.iloc[k] = capital + exposure * (at["net"] if charge_costs else at["gross"])
        earned = exposure * (result["net"] if charge_costs else result["gross"])
        equity = capital + earned
        curve.iloc[b + 1:] = equity
        trades.append({"strategy": rule["id"], "signal_date": str(t.index[i].date()),
                       "entry_date": str(t.index[a].date()), "exit_date": str(t.index[b].date()),
                       "entry_time": start.isoformat(), "exit_time": end.isoformat(),
                       "side": rule["side"], "entry_reference": entry, "exit_reference": exit_price,
                       **result, "pnl": earned, "equity": equity, "timing": timing,
                       "costs_charged": charge_costs, "cost_config": config_hash(c)})
        # A position exiting at today's close permits a new signal recorded after that close.
        available_after = b
        if equity <= 0:
            curve.iloc[b:] = equity
            break
    tr = pd.DataFrame(trades)
    returns = np.array([x["net"] if charge_costs else x["gross"] for x in trades])
    dd = curve / curve.cummax() - 1
    losses = -returns[returns < 0].sum() if len(returns) else 0
    stats = {"trades": len(trades), "return": equity / c["initial_equity"] - 1,
             "max_drawdown": float(dd.min()), "mean_trade": float(returns.mean()) if len(returns) else None,
             "win_rate": float((returns > 0).mean()) if len(returns) else None,
             "profit_factor": float(returns[returns > 0].sum() / losses) if losses else None,
             "terminal_equity": equity}
    return tr, curve, stats


def summarize_periods(trades):
    if trades.empty:
        return []
    rows = []
    for year, g in trades.groupby(pd.to_datetime(trades["entry_date"]).dt.year):
        rows.append([str(year),len(g),float(g["gross"].mean()),float(g["net"].mean()),float((g["net"]>0).mean())])
    return rows


def bootstrap_mean_interval(trades, seed=1701):
    """Calendar-year block resampling; uncertainty diagnostic, not a profitability guarantee."""
    if len(trades) < 20:
        return None
    groups = [g["net"].to_numpy() for _,g in trades.groupby(pd.to_datetime(trades["entry_date"]).dt.year)]
    if len(groups)<4:
        return None
    rng=np.random.default_rng(seed)
    means=[]
    for _ in range(2000):
        draw=np.concatenate([groups[i] for i in rng.integers(0,len(groups),len(groups))])
        means.append(float(draw.mean()))
    return [float(x) for x in np.quantile(means,[.025,.975])]
