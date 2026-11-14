"""Large one-day moves among the biggest index holdings: a single-stock shock changes what an index signal means.

An online refresh downloads three months of daily closes for the ten companies in thesis/earnings.py (Yahoo,
adjusted) to data/raw/megacaps.csv; offline builds only read it. A move is flagged when it is at least
THRESHOLD in either direction on the latest session. Context only: nothing here is scored.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from .data import last_known_session
from .earnings import COMPANIES

FILE = Path("data/raw/megacaps.csv")
THRESHOLD = 0.04


def yahoo_closes(symbols: list[str]) -> pd.DataFrame:
    import yfinance as yf
    return yf.download(symbols, period="3mo", interval="1d", auto_adjust=True, progress=False)["Close"]


def refresh(root: Path, download=yahoo_closes) -> dict:
    frame = download([s for s, _ in COMPANIES])
    if frame is None or frame.empty or len(frame) < 20:
        raise ValueError("price download returned too little data")  # the caller keeps the saved copy
    table = (frame.rename_axis("date").reset_index().melt(id_vars="date", var_name="ticker", value_name="close").dropna())
    table["date"] = pd.to_datetime(table["date"]).dt.strftime("%Y-%m-%d")
    path = Path(root) / FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    table.to_csv(temp, index=False)
    temp.replace(path)
    return {"tickers": int(table["ticker"].nunique()), "through": table["date"].max()}


def build(root: Path, now: pd.Timestamp, latest_close: str | None) -> dict:
    path = Path(root) / FILE
    if not path.exists():
        return {"status": "unavailable", "rows": [], "flagged": [],
                "reason": "Large-holding prices have not been downloaded yet; the next online refresh fetches them."}
    table = pd.read_csv(path, parse_dates=["date"])
    wide = table.pivot(index="date", columns="ticker", values="close").sort_index()
    wide = wide[wide.index <= last_known_session(now)]
    if len(wide) < 3:
        return {"status": "unavailable", "rows": [], "flagged": [], "reason": "Not enough saved prices."}
    day = wide.index[-1]
    moves = wide.pct_change()
    names = dict(COMPANIES)
    rows = []
    for symbol in wide.columns:
        move = moves[symbol].iloc[-1]
        if pd.isna(move):
            continue
        typical = moves[symbol].abs().iloc[-61:-1].median()
        rows.append({"symbol": symbol, "name": names.get(symbol, symbol), "move": float(move),
                     "typical_move": float(typical) if pd.notna(typical) else None, "flagged": bool(abs(move) >= THRESHOLD)})
    rows.sort(key=lambda r: -abs(r["move"]))
    session = f"{day:%Y-%m-%d}"
    return {"status": "ok", "session": session, "rows": rows, "flagged": [r for r in rows if r["flagged"]],
            "current": latest_close is None or session == latest_close, "threshold": THRESHOLD,
            "note": "One-day moves of the ten largest index holdings on the latest saved session (Yahoo, adjusted "
                    "closes). Flagged at 4% or more either way."}
