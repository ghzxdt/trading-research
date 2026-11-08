"""ETF expressions for each index view and what several leverage levels would have meant in loss terms.

No size is recommended (sizing stays blocked until a strategy has forward evidence). The user set no maximum
drawdown or leverage, so outcomes are shown at 1x, 2x, 3x, 5x and 10x of the index instead of one allowed size.
The thesis shows ETFs only (user, 2026-11-08); Kalshi data keeps collecting for later use.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

from .regime import VIX_BUCKETS, vix_bucket

LEVELS = (1, 2, 3, 5, 10)
UNDERLYINGS = (
    ("S&P 500", "SPY", (("SPY", 1), ("UPRO", 3), ("SPXU", -3))),
    ("Nasdaq-100", "QQQ", (("QQQ", 1), ("TQQQ", 3), ("SQQQ", -3))),
    ("Russell 2000", "IWM", (("IWM", 1), ("TNA", 3))),
)


def latest_spreads(root: Path, symbols) -> dict:
    """Most recent sampled share spread per symbol from the free liquidity samples, if any."""
    folder = Path(root) / "data" / "liquidity" / "samples"
    found = {}
    for path in sorted(folder.glob("*.jsonl"), reverse=True)[:10]:
        for line in reversed(path.read_text(encoding="utf-8").splitlines()):
            try:
                row = json.loads(line)
            except ValueError:
                continue
            symbol = row.get("symbol")
            if symbol in symbols and symbol not in found and row.get("share_spread_bps") is not None:
                found[symbol] = {"spread_bps": row["share_spread_bps"], "sampled_at": row.get("sampled_at")}
        if len(found) == len(symbols):
            break
    return found


def instrument(symbol: str, factor: int, frame: pd.DataFrame | None, spread: dict | None) -> dict:
    row = {"symbol": symbol, "factor": factor,
           "kind": "1x ETF" if factor == 1 else f"{abs(factor)}x {'inverse ' if factor < 0 else ''}ETF, resets daily"}
    if frame is None or frame.empty:
        return {**row, "status": "unavailable", "reason": "No saved daily history for this ETF yet."}
    tail = frame.iloc[-20:]
    return {**row, "status": "ok", "date": f"{frame.index[-1]:%Y-%m-%d}", "close": float(frame["close"].iloc[-1]),
            "dollar_volume_20d": float((tail["close"] * tail["volume"]).mean()),
            "spread_bps": (spread or {}).get("spread_bps"), "spread_sampled_at": (spread or {}).get("sampled_at")}


def move_history(frame: pd.DataFrame, vix: pd.Series, current_vix: float | None) -> dict:
    """The underlying's 1-day and 5-day moves on days when the prior close's VIX was in today's bucket."""
    close = frame["close"]
    prior_vix = vix.reindex(close.index).shift(1)
    one = close.pct_change()
    five = close.shift(-4) / close.shift(1) - 1  # five sessions starting today, measured from yesterday's close
    bucket = vix_bucket(current_vix) if current_vix is not None else None
    mask = prior_vix.map(vix_bucket) == bucket if bucket else pd.Series(False, index=close.index)
    days_1, days_5 = one[mask].dropna(), five[mask].dropna()
    if len(days_1) < 50:
        return {"status": "insufficient", "bucket": bucket, "days": int(len(days_1))}
    return {"status": "ok", "bucket": bucket, "since": f"{close.index[0]:%Y-%m-%d}", "days": int(len(days_1)),
            "worst_1d": float(days_1.min()), "worst_1d_date": f"{days_1.idxmin():%Y-%m-%d}",
            "p01_1d": float(days_1.quantile(0.01)), "best_1d": float(days_1.max()),
            "worst_5d": float(days_5.min()) if len(days_5) else None,
            "p01_5d": float(days_5.quantile(0.01)) if len(days_5) >= 100 else None}


def leverage_rows(daily_move: float | None, history: dict) -> list[dict]:
    rows = []
    for level in LEVELS:
        def equity(x):
            return None if x is None else max(level * x, -1.0)
        rows.append({"leverage": level, "index_move_to_lose_all": -1 / level,
                     "one_sd_day": None if daily_move is None else level * daily_move,
                     "p01_day": equity(history.get("p01_1d")), "worst_day": equity(history.get("worst_1d")),
                     "worst_5d": equity(history.get("worst_5d"))})
    return rows


def build(root: Path, etfs: dict, vix: pd.Series, implied_spy_move: float | None) -> dict:
    current_vix = float(vix.iloc[-1]) if len(vix) else None
    symbols = [s for _, _, group in UNDERLYINGS for s, _ in group]
    spreads = latest_spreads(root, set(symbols))
    out = []
    for name, base, group in UNDERLYINGS:
        frame = etfs.get(base)
        if frame is None:
            continue
        realized = float(frame["close"].pct_change().iloc[-20:].std(ddof=1)) if len(frame) > 21 else None
        if base == "SPY" and implied_spy_move is not None:
            move, basis = implied_spy_move, "VIX-implied (options market's expected S&P 500 move)"
        else:
            move, basis = realized, "Last 20 sessions' realized volatility (no saved implied volatility index)"
        history = move_history(frame, vix, current_vix)
        out.append({"underlying": name, "base": base, "one_sd_move": move, "move_basis": basis,
                    "instruments": [instrument(s, f, etfs.get(s), spreads.get(s)) for s, f in group],
                    "history": history, "levels": leverage_rows(move, history)})
    return {"underlyings": out, "vix": current_vix, "vix_bucket": vix_bucket(current_vix) if current_vix else None,
            "notes": [
                "No position size is recommended: sizing stays blocked until a strategy has forward evidence.",
                "Loss figures are the underlying's historical move times the leverage, capped at -100% (the account "
                "is gone). Brokers issue margin calls and liquidate well before that point, at levels that depend on "
                "the broker and the instrument.",
                "3x ETFs reset daily, so over several days they can lose more (in choppy markets) or less than 3x "
                "the index. Their own price history starts in 2010.",
                "Above 3x needs margin, futures or another leveraged product; the figures show the exposure, not "
                "a way to get it.",
                f"Historical rows use days when the previous close's VIX was in today's bucket "
                f"({', '.join(label for _, _, label in VIX_BUCKETS)})."]}
