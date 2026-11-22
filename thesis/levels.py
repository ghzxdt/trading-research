"""Price levels for the Review page (review v2, 2026-11-21): moving averages, the 5-day-average exit's close,
ATR(14) and the latest swing points, for SPY, QQQ and IWM, from this app's daily bars.

These are untested chart levels: context for the user's charts and alerts, never a signal. ATR(14) also scales
"near a trigger" on the pages (spec step 5.15: 3% is less than a day's move with VIX at 36).
"""
from __future__ import annotations

import pandas as pd

SYMBOLS = ("SPY", "QQQ", "IWM")
ATR_DAYS = 14
SWING = 3  # a swing high is a session whose high is above the highs of the 3 sessions on each side (a low: below)
LOOKBACK = 120  # sessions searched for the latest swing points

DEFINITIONS = {
    "exit_close": "The close that exits the 5-day-average rule at the next session: the 5-day average includes "
                  "that close, so any close above the mean of the last 4 closes exits.",
    "atr14": "Average true range over 14 sessions (Wilder): the typical daily range including gaps.",
    "swing": f"The most recent session whose high (low) is above (below) the {SWING} sessions on each side, within "
             f"the last {LOOKBACK} sessions; it needs {SWING} sessions after it to be confirmed.",
}


def atr(frame: pd.DataFrame | None, n: int = ATR_DAYS) -> float | None:
    """Wilder's average true range at the last bar, or None without enough high/low/close data."""
    if frame is None or len(frame) < n + 1 or not {"high", "low", "close"} <= set(frame.columns):
        return None
    previous = frame["close"].shift()
    true_range = pd.concat([frame["high"] - frame["low"], (frame["high"] - previous).abs(),
                            (frame["low"] - previous).abs()], axis=1).max(axis=1).iloc[1:]
    value = true_range.ewm(alpha=1 / n, adjust=False, min_periods=n).mean().iloc[-1]
    return float(value) if pd.notna(value) else None


def swings(frame: pd.DataFrame | None, k: int = SWING, lookback: int = LOOKBACK) -> dict:
    """The latest confirmed swing high and swing low: {"high": {"date", "price"} or None, "low": ...}."""
    out = {"high": None, "low": None}
    if frame is None or len(frame) < 2 * k + 1 or not {"high", "low"} <= set(frame.columns):
        return out
    tail = frame.iloc[-lookback:]
    highs, lows = tail["high"].to_numpy(float), tail["low"].to_numpy(float)
    for i in range(len(tail) - k - 1, k - 1, -1):
        h, low = highs[i - k:i + k + 1], lows[i - k:i + k + 1]
        if out["high"] is None and (h < highs[i]).sum() == 2 * k:
            out["high"] = {"date": f"{tail.index[i]:%Y-%m-%d}", "price": float(highs[i])}
        if out["low"] is None and (low > lows[i]).sum() == 2 * k:
            out["low"] = {"date": f"{tail.index[i]:%Y-%m-%d}", "price": float(lows[i])}
        if out["high"] and out["low"]:
            break
    return out


def build(etfs: dict, symbols=SYMBOLS) -> dict:
    out = {}
    for symbol in symbols:
        frame = etfs.get(symbol)
        if frame is None or frame.empty:
            continue
        close = frame["close"]
        mean = lambda n: float(close.iloc[-n:].mean()) if len(close) >= n else None  # noqa: E731
        points = swings(frame)
        out[symbol] = {"date": f"{close.index[-1]:%Y-%m-%d}", "close": float(close.iloc[-1]),
                       "change_1d": float(close.iloc[-1] / close.iloc[-2] - 1) if len(close) >= 2 else None,
                       "sma5": mean(5), "exit_close": mean(4), "sma20": mean(20), "sma50": mean(50), "sma200": mean(200),
                       "atr14": atr(frame), "swing_high": points["high"], "swing_low": points["low"]}
    return {"symbols": out, "definitions": DEFINITIONS}
