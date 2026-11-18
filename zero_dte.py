"""Same-day (0DTE) options research data for SPY, QQQ and IWM. Collection and description only.

Checked 2026-11-13: Cboe's free delayed-quotes feed lists an expiry every trading day for SPY, QQQ and IWM
(TQQQ lists Monday, Wednesday and Friday). The feed is about 15 minutes delayed and indicative: its prices are
not executable quotes, and nothing here is a trade signal.

At each snapshot (10:00 AM, 10:30, 12:30, 2:30 and 3:50 PM ET from the scheduled collection) this saves, per
ETF, the contracts expiring today within 3% of the share price, and a summary line: the at-the-money straddle's
bid, ask and mid, the implied move (straddle mid / share price) and the spread as a share of the premium.

Why a held-to-close view works with free data: an option expiring today settles from the closing price alone,
so only the entry needs an option quote. summary() compares each snapshot's implied move with the move the ETF
then made to the close, and the straddle's value at the close with its cost (at mid, and at the ask as the worst
case). One observation per ETF per day: it takes about 60 sessions before these averages say anything.

Files (git-ignored, in the nightly data backup): data/zero_dte/chains/<date>.jsonl, data/zero_dte/summary.csv.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

import pandas as pd
import requests

NY = "America/New_York"
SYMBOLS = ("SPY", "QQQ", "IWM")
URL = "https://cdn.cboe.com/api/global/delayed_quotes/options/{symbol}.json"
FOLDER = Path("data/zero_dte")
SUMMARY = FOLDER / "summary.csv"
BAND = 0.03
COLUMNS = ["session", "snapshot_et", "feed_time", "symbol", "spot", "strike", "call_bid", "call_ask", "put_bid", "put_ask",
           "straddle_mid", "straddle_ask", "implied_move", "spread_share", "contracts"]


def _get(url: str) -> dict:
    from stage1.sources import HEADERS
    response = requests.get(url, headers=HEADERS, timeout=30)
    response.raise_for_status()
    return response.json()


def parse(payload: dict, symbol: str, session: str) -> dict | None:
    """Today's contracts near the money from one Cboe delayed-quotes reply, plus the at-the-money straddle."""
    data = payload.get("data") or {}
    spot = data.get("current_price") or data.get("close")
    if not spot:
        return None
    code = pd.Timestamp(session).strftime("%y%m%d")
    rows = []
    for option in data.get("options") or []:
        name = str(option.get("option") or "")
        if not name.startswith(symbol + code) or len(name) != len(symbol) + 15:
            continue
        strike = int(name[-8:]) / 1000
        if abs(strike / spot - 1) > BAND:
            continue
        rows.append({"k": strike, "r": name[len(symbol) + 6], "bid": option.get("bid"), "ask": option.get("ask"),
                     "iv": option.get("iv"), "vol": option.get("volume"), "oi": option.get("open_interest"),
                     "delta": option.get("delta")})
    if not rows:
        return None
    out = {"symbol": symbol, "session": session, "feed_time": payload.get("timestamp"), "spot": float(spot), "rows": rows}
    quoted = {}
    for row in rows:
        if row["bid"] and row["ask"] and row["ask"] >= row["bid"] > 0:
            quoted.setdefault(row["k"], {})[row["r"]] = row
    both = [k for k, sides in quoted.items() if {"C", "P"} <= set(sides)]
    if both:
        strike = min(both, key=lambda k: abs(k - spot))
        call, put = quoted[strike]["C"], quoted[strike]["P"]
        mid = (call["bid"] + call["ask"] + put["bid"] + put["ask"]) / 2
        ask = call["ask"] + put["ask"]
        out["straddle"] = {"strike": strike, "call_bid": call["bid"], "call_ask": call["ask"], "put_bid": put["bid"],
                           "put_ask": put["ask"], "mid": mid, "ask": ask, "implied_move": mid / spot,
                           "spread_share": (ask - (call["bid"] + put["bid"])) / mid if mid > 0 else None}
    return out


def snapshot(root: Path, now: pd.Timestamp, symbols=SYMBOLS, get=_get) -> dict:
    """Save one snapshot per ETF. Regular session of a trading day only (9:45 AM to the close: 4:00 PM ET, or
    1:00 PM on an early close since 2026-11-18)."""
    from intraday.calendar import close_minutes
    from validation import equity_sessions
    local = now.tz_convert(NY)
    day = local.tz_localize(None).normalize()
    minutes = local.hour * 60 + local.minute
    close = close_minutes(day) if len(equity_sessions(day, day)) == 1 else None
    if not close or not 9 * 60 + 45 <= minutes < close:
        return {"saved": 0, "skipped": "outside the regular session"}
    session = f"{day:%Y-%m-%d}"
    saved, failed, lines = [], [], []
    for symbol in symbols:
        try:
            got = parse(get(URL.format(symbol=symbol)), symbol, session)
            if not got:
                raise ValueError("no contracts expiring today near the money")
            got["snapshot_et"] = local.isoformat(timespec="seconds")
            lines.append(got)
            saved.append(symbol)
        except Exception as exc:
            failed.append(f"{symbol}: {str(exc)[:120]}")
    if lines:
        chains = Path(root) / FOLDER / "chains" / f"{session}.jsonl"
        chains.parent.mkdir(parents=True, exist_ok=True)
        with chains.open("a", encoding="utf-8", newline="\n") as stream:
            for line in lines:
                stream.write(json.dumps(line, sort_keys=True) + "\n")
        path = Path(root) / SUMMARY
        new = not path.exists()
        with path.open("a", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=COLUMNS)
            if new:
                writer.writeheader()
            for line in lines:
                s = line.get("straddle") or {}
                writer.writerow({"session": session, "snapshot_et": line["snapshot_et"], "feed_time": line["feed_time"],
                                 "symbol": line["symbol"], "spot": line["spot"], "strike": s.get("strike"),
                                 "call_bid": s.get("call_bid"), "call_ask": s.get("call_ask"), "put_bid": s.get("put_bid"),
                                 "put_ask": s.get("put_ask"), "straddle_mid": s.get("mid"), "straddle_ask": s.get("ask"),
                                 "implied_move": s.get("implied_move"), "spread_share": s.get("spread_share"),
                                 "contracts": len(line["rows"])})
    return {"saved": len(saved), "symbols": saved, "failed": failed}


def update_indexes(root: Path, get=None) -> dict:
    """Evening: save Cboe's one-day and nine-day VIX histories (data/raw, re-downloadable) for later comparison."""
    from stage1.sources import CBOE_URL, HEADERS
    out = {}
    for name in ("VIX1D", "VIX9D"):
        try:
            text = get(name) if get else requests.get(CBOE_URL.format(name=name), headers=HEADERS, timeout=30).text
            lines = text.strip().splitlines()
            if len(lines) < 100 or not lines[0].upper().startswith("DATE"):
                raise ValueError("unexpected file")
            path = Path(root) / "data" / "raw" / f"{name}.csv"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
            out[name] = lines[-1].split(",")[0]
        except Exception as exc:
            out[name] = f"failed: {str(exc)[:80]}"
    return out


RAW_CLOSES = FOLDER / "raw_closes.csv"


def _yahoo_raw(symbols) -> pd.DataFrame:
    import yfinance as yf
    frame = yf.download(list(symbols), period="1mo", auto_adjust=False, progress=False, group_by="ticker", threads=True)
    rows = []
    for symbol in symbols:
        closes = frame[symbol]["Close"].dropna()
        rows += [{"session": f"{day:%Y-%m-%d}", "symbol": symbol, "close": float(value)} for day, value in closes.items()]
    return pd.DataFrame(rows)


def update_raw_closes(root: Path, now: pd.Timestamp | None = None, fetch=_yahoo_raw, symbols=SYMBOLS) -> str:
    """Evening: keep each session's raw (not dividend-adjusted) close, which is what an expiring option settles on.

    Added 2026-11-18 (review A3): the outcome compared raw strikes and spot with the app's dividend-adjusted closes,
    which sit below the raw close on every session before a later ex-dividend date. Only completed sessions are
    kept (the session's close is final 30 minutes after 4 PM ET); the first value saved for a session stands."""
    from validation import equity_sessions
    now = (now or pd.Timestamp.now(tz=NY)).tz_convert(NY)
    today = now.tz_localize(None).normalize()
    done_through = today if now.hour * 60 + now.minute >= 16 * 60 + 30 else today - pd.Timedelta(days=1)
    path = Path(root) / RAW_CLOSES
    old = pd.read_csv(path) if path.exists() else pd.DataFrame(columns=["session", "symbol", "close", "fetched_utc"])
    window = equity_sessions(done_through - pd.Timedelta(days=45), done_through)
    if not len(window):
        return "no completed session to save"
    done_through = window[-1]
    sessions = {f"{d:%Y-%m-%d}" for d in window}
    got = fetch(symbols)
    got = got[got["session"].isin(sessions) & (got["close"] > 0)]
    known = set(zip(old["session"], old["symbol"]))
    new = got[[(s, y) not in known for s, y in zip(got["session"], got["symbol"])]].assign(
        fetched_utc=pd.Timestamp.now(tz="UTC").isoformat(timespec="seconds"))
    if len(new):
        path.parent.mkdir(parents=True, exist_ok=True)
        pd.concat([old, new]).sort_values(["session", "symbol"]).to_csv(path, index=False, lineterminator="\n")
    return f"{len(new)} new raw closes (through {done_through:%Y-%m-%d})"


def _raw_closes(root: Path) -> dict:
    path = Path(root) / RAW_CLOSES
    if not path.exists():
        return {}
    table = pd.read_csv(path)
    return {(r["session"], r["symbol"]): float(r["close"]) for r in table.to_dict("records")}


def summary(root: Path, etfs: dict) -> dict:
    """Implied against realised move for the first usable snapshot of each ETF and day, with the count.

    Settled on the session's raw close (update_raw_closes), never the dividend-adjusted daily history: strikes
    and the snapshot's spot are raw prices. A day without its raw close yet stays unsettled."""
    raw = _raw_closes(root)
    path = Path(root) / SUMMARY
    if not path.exists():
        return {"status": "empty", "days": 0, "rows": [], "latest": [],
                "reason": "No same-day option snapshot yet. The first is taken at 10:00 AM ET on a trading day."}
    table = pd.read_csv(path)
    table = table[table["straddle_mid"].notna() & (table["straddle_mid"] > 0)]
    if table.empty:
        return {"status": "empty", "days": 0, "rows": [], "latest": [], "reason": "No snapshot had a two-sided straddle quote."}
    first = table.sort_values("snapshot_et").groupby(["session", "symbol"], as_index=False).first()
    rows = []
    for symbol in SYMBOLS:
        mine = first[first["symbol"] == symbol]
        settled, waiting = [], 0
        for r in mine.to_dict("records"):
            close = raw.get((r["session"], symbol))
            if close is None:
                waiting += 1
                continue
            value = abs(close - r["strike"])
            settled.append({"implied": r["implied_move"], "realised": abs(close / r["spot"] - 1),
                            "pnl_mid": value / r["straddle_mid"] - 1, "pnl_ask": value / r["straddle_ask"] - 1,
                            "spread": r["spread_share"]})
        mean = lambda key: sum(s[key] for s in settled) / len(settled) if settled else None  # noqa: E731
        rows.append({"symbol": symbol, "days_collected": int(len(mine)), "days_settled": len(settled),
                     "days_waiting_for_raw_close": waiting,
                     "mean_implied": mean("implied"), "mean_realised": mean("realised"),
                     "realised_above_implied": sum(s["realised"] > s["implied"] for s in settled) / len(settled) if settled else None,
                     "straddle_mean_at_mid": mean("pnl_mid"), "straddle_mean_at_ask": mean("pnl_ask"),
                     "mean_spread_share": mean("spread")})
    last_day = table["session"].max()
    latest = (table[table["session"] == last_day].sort_values("snapshot_et").groupby("symbol", as_index=False).last()
              [["symbol", "snapshot_et", "feed_time", "spot", "strike", "straddle_mid", "implied_move", "spread_share"]])
    return {"status": "ok", "days": int(first["session"].nunique()), "rows": rows, "latest_session": last_day,
            "latest": json.loads(latest.to_json(orient="records")),
            "note": "Research data from Cboe's delayed feed (about 15 minutes behind; not executable quotes). "
                    "Implied move is the at-the-money straddle's mid price over the share price at the day's first "
                    "snapshot; realised is the move from then to the session's raw close (Yahoo, not dividend-"
                    "adjusted, saved each evening). The straddle result is its value at that close against its cost, "
                    "per day, before fees. About 60 settled days are needed before these averages mean anything."}
