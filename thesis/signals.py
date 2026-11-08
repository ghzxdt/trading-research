"""Today's state of the backtester's registered oversold rules, with that app's evidence (ETF pricing only).

The rules are recomputed here from the saved daily data, so this app never needs the backtester to run. The
backtester's export lists every date each rule fired; the dates are compared over the common history so a
definition drift between the two apps shows up as a mismatch instead of silently wrong evidence. If the export
is missing, the evidence says "unavailable".
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import numpy as np
import pandas as pd

DEFAULT_EXPORT = Path("C:/Users/gzdt/trading-backtester/exports/trade_simulation.json")
SYMBOLS = ("SPY", "QQQ", "IWM")
EVIDENCE_SYMBOLS = ("SPY", "QQQ")  # the backtester simulated these two (long histories)
EXIT_LABELS = {"hold_5": "Hold 5 sessions", "close_above_sma5": "First close above the 5-day average (max 10)"}
MODE_LABELS = {"etf_close": "Buy at the signal close", "etf_next_open": "Buy at the next open"}


def rsi(close: pd.Series, n: int) -> pd.Series:
    """Wilder RSI, identical to the backtester's definition (blank until its full lookback)."""
    change = close.diff()
    gain = change.clip(lower=0).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    loss = (-change.clip(upper=0)).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    out = 100 - 100 / (1 + gain / loss)
    return out.where(loss != 0, 100.0).where(gain.notna())


def lower_band(close: pd.Series, n: int = 20, width: float = 2.0) -> pd.Series:
    mid = close.rolling(n, min_periods=n).mean()
    return mid - close.rolling(n, min_periods=n).std(ddof=0) * width


RULES = {
    "rsi2_below_10": ("RSI(2) below 10", lambda c: rsi(c, 2) < 10, lambda c: rsi(c, 2)),
    "rsi14_below_30": ("RSI(14) below 30", lambda c: rsi(c, 14) < 30, lambda c: rsi(c, 14)),
    "bollinger_lower_close": ("Close below the lower Bollinger band (20, 2)", lambda c: c < lower_band(c),
                              lambda c: lower_band(c)),
}


def export_path() -> Path:
    return Path(os.environ.get("THESIS_BACKTESTER_EXPORT") or DEFAULT_EXPORT)


def load_export(path: Path | None = None) -> tuple[dict | None, dict]:
    path = Path(path or export_path())
    if not path.exists():
        return None, {"status": "unavailable", "path": str(path),
                      "reason": "The backtester's trade-simulation export was not found. Run 'Run trade simulation' "
                                "in the Trading Backtester app."}
    raw = path.read_bytes()
    try:
        payload = json.loads(raw)
        if payload.get("kind") != "trade_simulation" or payload.get("schema") != 1:
            raise ValueError("unexpected export format")
    except (ValueError, AttributeError) as exc:
        return None, {"status": "invalid", "path": str(path), "reason": f"Export unreadable: {exc}"}
    return payload, {"status": "ok", "path": str(path), "sha256": hashlib.sha256(raw).hexdigest(),
                     "generated_at": payload.get("generated_at"), "code": payload.get("code"),
                     "data_fingerprint": payload.get("data_fingerprint"), "report": payload.get("report")}


def trigger_close(close: pd.Series, rule, tolerance: float = 1e-4) -> float | None:
    """Highest next close that would make the rule fire, found with the rule itself (bisection)."""
    last = float(close.iloc[-1])
    next_day = close.index[-1] + pd.Timedelta(days=1)

    def fires(price: float) -> bool:
        return bool(rule(pd.concat([close, pd.Series([price], index=[next_day])])).iloc[-1])

    low, high = last * 0.5, last * 1.5
    if not fires(low):
        return None
    if fires(high):
        return high
    while high - low > last * tolerance:
        mid = (low + high) / 2
        low, high = (mid, high) if fires(mid) else (low, mid)
    return low


def crosscheck(local: pd.Series, exported: dict | None) -> dict:
    if not exported:
        return {"status": "unavailable"}
    end = pd.Timestamp(exported["last_date"])
    mine = {f"{d:%Y-%m-%d}" for d in local.index[local.fillna(False).to_numpy(bool)] if d <= end}
    theirs = set(exported.get("dates", []))
    differ = sorted(mine ^ theirs)
    return {"status": "match" if not differ else "mismatch", "checked_through": exported["last_date"],
            "dates_checked": len(mine | theirs), "differences": differ[:10]}


def _evidence(payload: dict | None, symbol: str, signal: str) -> list[dict]:
    if not payload:
        return []
    rows = [s for s in payload.get("strategies", []) if s["symbol"] == symbol and s["signal"] == signal]
    for row in rows:
        row["exit_label"], row["mode_label"] = EXIT_LABELS.get(row["exit"], row["exit"]), MODE_LABELS.get(row["mode"], row["mode"])
    return rows


def build(etfs: dict, payload: dict | None = None) -> dict:
    out = []
    for symbol in SYMBOLS:
        frame = etfs.get(symbol)
        if frame is None or len(frame) < 60:
            continue
        close = frame["close"]
        for name, (label, rule, value) in RULES.items():
            fired = rule(close)
            dates = close.index[fired.fillna(False).to_numpy(bool)]
            exported = (payload or {}).get("signal_days", {}).get(f"{symbol}:{name}")
            level = value(close).iloc[-1]
            out.append({"symbol": symbol, "signal": name, "label": label, "date": f"{close.index[-1]:%Y-%m-%d}",
                        "fired": bool(fired.iloc[-1]), "value": float(level) if np.isfinite(level) else None,
                        "close": float(close.iloc[-1]),
                        "last_fired": f"{dates[-1]:%Y-%m-%d}" if len(dates) else None,
                        "times_fired_1y": int((dates > close.index[-1] - pd.DateOffset(years=1)).sum()),
                        "trigger_close": trigger_close(close, rule),
                        "sma5": float(close.iloc[-5:].mean()),
                        "evidence": _evidence(payload, symbol, name) if symbol in EVIDENCE_SYMBOLS else [],
                        "evidence_note": None if symbol in EVIDENCE_SYMBOLS else
                        "Not simulated: IWM's saved history starts in 2010, so it has no 1993-2009 holdout.",
                        "crosscheck": crosscheck(fired, exported) if symbol in EVIDENCE_SYMBOLS else {"status": "not_applicable"}})
    return {"signals": out}
