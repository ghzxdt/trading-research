"""Second-source check of the app's ETF prices (Yahoo) against FRED's index closes.

FRED publishes the S&P 500 (last 10 years) and Nasdaq-100 (since 1986) daily closes, free and
without a key. SPY's and QQQ's dividend-adjusted daily returns normally match their index's to
about 0.03%, and on 99% of days to within about 0.2%. A gap above 0.25% usually means a bad
print in one of the two sources, or a day of extreme closing moves (March 2020, April 9 2025).

An online refresh downloads the FRED series to data/raw/crosscheck/; offline builds only read
them. The result is shown on the Data quality tab. It does not change the gate that controls
paper decisions.
"""
from __future__ import annotations

import io
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

SERIES = {"SP500": ("spy", "S&P 500"), "NASDAQ100": ("qqq", "Nasdaq-100")}
URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}"
HEADERS = {"User-Agent": "index-research-crosscheck/0.1 (personal research script)"}
FOLDER = Path("data/raw/crosscheck")
TOLERANCE = 0.0025  # 0.25% difference between two daily returns
WINDOW = 60  # latest sessions compared


def parse(text: str) -> pd.Series:
    frame = pd.read_csv(io.StringIO(text))
    frame.columns = ["date", "close"]
    frame["close"] = pd.to_numeric(frame["close"], errors="coerce")  # FRED marks holidays with "."
    frame = frame.dropna()
    series = pd.Series(frame["close"].to_numpy(), index=pd.to_datetime(frame["date"]), name="close").sort_index()
    if series.empty or (series <= 0).any() or not series.index.is_unique:
        raise ValueError("FRED series is empty, non-positive or has duplicate dates")
    return series


def refresh(root: Path, get=requests.get) -> dict:
    """Download each series; keep the previous copy if a download fails or looks wrong."""
    folder = Path(root) / FOLDER
    folder.mkdir(parents=True, exist_ok=True)
    status = {}
    for series in SERIES:
        stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        try:
            response = get(URL.format(series=series), headers=HEADERS, timeout=60)
            response.raise_for_status()
            closes = parse(response.text)
            if len(closes) < 250:
                raise ValueError(f"only {len(closes)} observations")
            temp = folder / f"{series}.tmp"
            temp.write_text(response.text, encoding="utf-8")
            temp.replace(folder / f"{series}.csv")
            status[series] = {"ok": True, "observed_at": stamp, "last": str(closes.index[-1].date())}
        except Exception as exc:
            status[series] = {"ok": False, "attempted_at": stamp, "error": str(exc)}
    (folder / "status.json").write_text(json.dumps(status, indent=2), encoding="utf-8")
    return status


def load(root: Path) -> dict[str, pd.Series]:
    out = {}
    for series in SERIES:
        path = Path(root) / FOLDER / f"{series}.csv"
        if path.exists():
            try:
                out[series] = parse(path.read_text(encoding="utf-8"))
            except ValueError:
                pass
    return out


def compare(table: pd.DataFrame, closes: dict[str, pd.Series], window: int = WINDOW, tolerance: float = TOLERANCE) -> dict:
    """Day-by-day gap between the ETF's daily return in the app's table and its index's on FRED."""
    report = {}
    for series, (etf, name) in SERIES.items():
        column = f"{etf}_ret"
        if series not in closes or column not in table:
            report[series] = {"status": "UNAVAILABLE", "etf": etf.upper(), "index": name,
                              "reason": "No FRED data saved yet; the next online refresh downloads it."}
            continue
        both = pd.DataFrame({"etf": table[column], "index": closes[series].pct_change()}).dropna().iloc[-window:]
        if both.empty:
            report[series] = {"status": "UNAVAILABLE", "etf": etf.upper(), "index": name, "reason": "No overlapping dates."}
            continue
        gap = both["etf"] - both["index"]
        flagged = gap[gap.abs() > tolerance]
        report[series] = {"status": "CHECK" if len(flagged) else "PASS", "etf": etf.upper(), "index": name,
                          "compared": len(both), "first": str(both.index[0].date()), "last": str(both.index[-1].date()),
                          "median_gap_pct": round(float(gap.abs().median()) * 100, 4),
                          "max_gap_pct": round(float(gap.abs().max()) * 100, 4),
                          "flagged": [{"date": str(day.date()), "gap_pct": round(float(value) * 100, 3)} for day, value in flagged.items()]}
    return report


def quality_row(report: dict) -> list[str]:
    """One row for the Data quality table: check, observed, state, meaning."""
    states = {entry["status"] for entry in report.values()}
    state = ("CHECK" if "CHECK" in states else "UNAVAILABLE" if states == {"UNAVAILABLE"}
             else "PARTIAL" if "UNAVAILABLE" in states else "PASS")
    observed = "; ".join(
        f"{e['etf']} vs {e['index']}: {e['compared']} days to {e['last']}, largest gap {e['max_gap_pct']:.2f}%"
        if e["status"] in ("PASS", "CHECK") else f"{e['etf']} vs {e['index']}: unavailable" for e in report.values())
    flagged = [f"{e['etf']} {f['date']} ({f['gap_pct']:+.2f}%)" for e in report.values() for f in e.get("flagged", [])]
    meaning = (f"Yahoo's SPY/QQQ daily returns vs FRED's index closes over the latest {WINDOW} sessions; "
               f"gaps above {TOLERANCE * 100:.2f}% are listed. "
               + (f"Flagged: {', '.join(flagged[:6])}. " if flagged else "None flagged. ")
               + "Display only; it does not change the paper-log gate.")
    return ["Second-source prices (FRED)", observed, state, meaning]
