"""Latest economic release values: jobs, inflation and weekly jobless claims, from official free sources.

- BLS Public Data API v1 (no key, 25 requests a day; one request per online refresh): nonfarm payrolls,
  unemployment rate, average hourly earnings, CPI and core CPI.
- FRED (no key): weekly initial jobless claims (ICSA).

What this is not: these are the values as published today, revisions included. A first-release number needs
FRED's vintage archive (a free API key the user registers), and a "surprise" needs a market expectation, which
is not available for free. So the page shows the level and the change, never a surprise. Context only.
An online refresh downloads to data/raw/releases/releases.json; offline builds only read it.
"""
from __future__ import annotations

import io
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

BLS_URL = "https://api.bls.gov/publicAPI/v1/timeseries/data/"
FRED_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"
FILE = Path("data/raw/releases/releases.json")
SERIES = {"payrolls": "CES0000000001", "unemployment": "LNS14000000", "hourly_earnings": "CES0500000003",
          "cpi_sa": "CUSR0000SA0", "core_cpi_sa": "CUSR0000SA0L1E", "cpi_nsa": "CUUR0000SA0", "core_cpi_nsa": "CUUR0000SA0L1E"}
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) personal-research-script"}


def bls_series(year: int, post=requests.post) -> dict[str, list[dict]]:
    body = {"seriesid": list(SERIES.values()), "startyear": str(year - 2), "endyear": str(year)}
    response = post(BLS_URL, json=body, headers={"Content-Type": "application/json"}, timeout=40)
    response.raise_for_status()
    payload = response.json()
    if payload.get("status") != "REQUEST_SUCCEEDED":
        raise ValueError("BLS: " + "; ".join(payload.get("message") or ["request failed"])[:200])
    by_id = {s["seriesID"]: s["data"] for s in (payload.get("Results") or {}).get("series", [])}
    out = {}
    for name, series_id in SERIES.items():
        rows = []
        for item in by_id.get(series_id) or []:
            if not str(item.get("period", "")).startswith("M") or item["period"] == "M13":
                continue
            try:
                value = float(item["value"])
            except (TypeError, ValueError):
                continue  # BLS marks a missing month with "-"
            rows.append({"period": f"{item['year']}-{item['period'][1:]}", "value": value,
                         "preliminary": any((f or {}).get("code") == "P" for f in item.get("footnotes") or [])})
        out[name] = sorted(rows, key=lambda r: r["period"])
    return out


def fred_claims(get=requests.get) -> list[dict]:
    response = get(FRED_URL, params={"id": "ICSA"}, headers=HEADERS, timeout=40)
    response.raise_for_status()
    frame = pd.read_csv(io.StringIO(response.text))
    frame.columns = ["week", "value"]
    frame["value"] = pd.to_numeric(frame["value"], errors="coerce")
    return [{"week": str(r.week), "value": float(r.value)} for r in frame.dropna().tail(60).itertuples()]


def refresh(root: Path, bls=bls_series, claims=fred_claims) -> dict:
    path = Path(root) / FILE
    saved = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    status = {}
    for key, fetch in (("bls", lambda: bls(datetime.now(timezone.utc).year)), ("claims", claims)):
        try:
            got = fetch()
            if not got or (key == "bls" and not got.get("payrolls")):
                raise ValueError("empty reply")
            saved[key], saved[f"{key}_fetched_utc"] = got, datetime.now(timezone.utc).isoformat(timespec="seconds")
            status[key] = True
        except Exception as exc:  # keep the last good copy
            status[key] = f"failed: {str(exc)[:120]}"
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(saved, indent=1), encoding="utf-8")
    temp.replace(path)
    return status


def _month(period: str) -> str:
    return f"{pd.Timestamp(period + '-01'):%b %Y}"


def _change(rows: list[dict], back: int = 1) -> float | None:
    return rows[-1]["value"] / rows[-1 - back]["value"] - 1 if len(rows) > back else None


def build(root: Path, now: pd.Timestamp) -> dict:
    path = Path(root) / FILE
    if not path.exists():
        return {"status": "unavailable", "rows": [],
                "reason": "Release values have not been downloaded yet; the next online refresh fetches them."}
    saved = json.loads(path.read_text(encoding="utf-8"))
    fetched = saved.get("bls_fetched_utc") or saved.get("claims_fetched_utc")
    if fetched and pd.Timestamp(fetched) > now.tz_convert("UTC"):
        return {"status": "unavailable", "rows": [], "reason": "Not shown in a replay: the saved values were downloaded later."}
    bls, rows = saved.get("bls") or {}, []
    jobs = bls.get("payrolls") or []
    if len(jobs) >= 3:
        rows.append({"name": "Nonfarm payrolls", "period": _month(jobs[-1]["period"]), "preliminary": jobs[-1]["preliminary"],
                     "value": f"{jobs[-1]['value'] - jobs[-2]['value']:+,.0f}K jobs",
                     "previous": f"{jobs[-2]['value'] - jobs[-3]['value']:+,.0f}K", "source": "BLS"})
    rate = bls.get("unemployment") or []
    if len(rate) >= 2:
        rows.append({"name": "Unemployment rate", "period": _month(rate[-1]["period"]), "preliminary": rate[-1]["preliminary"],
                     "value": f"{rate[-1]['value']:.1f}%", "previous": f"{rate[-2]['value']:.1f}%", "source": "BLS"})
    for key, nsa, label in (("hourly_earnings", "hourly_earnings", "Average hourly earnings"),
                            ("cpi_sa", "cpi_nsa", "CPI"), ("core_cpi_sa", "core_cpi_nsa", "Core CPI")):
        monthly, yearly = bls.get(key) or [], bls.get(nsa) or []
        if len(monthly) >= 3 and len(yearly) >= 13 and yearly[-1]["period"] == monthly[-1]["period"]:
            rows.append({"name": label, "period": _month(monthly[-1]["period"]), "preliminary": monthly[-1]["preliminary"],
                         "value": f"{_change(monthly):+.2%} in the month · {_change(yearly, 12):+.1%} in a year",
                         "previous": f"{monthly[-2]['value'] / monthly[-3]['value'] - 1:+.2%} in the month", "source": "BLS"})
    claims = saved.get("claims") or []
    if len(claims) >= 4:
        average = sum(c["value"] for c in claims[-4:]) / 4
        rows.append({"name": "Initial jobless claims", "period": "week ending " + claims[-1]["week"], "preliminary": False,
                     "value": f"{claims[-1]['value']:,.0f}", "previous": f"{claims[-2]['value']:,.0f} · 4-week average {average:,.0f}",
                     "source": "FRED (ICSA)"})
    return {"status": "ok" if rows else "unavailable", "rows": rows, "fetched_utc": fetched,
            "reason": None if rows else "The saved release values are incomplete.",
            "note": "Values as published now, revisions included (P marks a preliminary figure). No market "
                    "expectation is available for free, so no surprise is shown. Yearly CPI uses the unadjusted "
                    "index, monthly the seasonally adjusted one, as BLS reports them."}
