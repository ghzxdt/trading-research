"""Credit spreads from FRED (free, no key): the market's price of default risk.

- BAA10Y: Moody's Baa corporate yield minus the 10-year Treasury, daily since 1986. The long history.
- BAMLH0A0HYM2: ICE BofA US High Yield option-adjusted spread. FRED shows only the last ~3 years (license).
- BAMLH0A3HYC: ICE BofA CCC & lower OAS, the riskiest bonds; also ~3 years on FRED.

Widening spreads usually come before or with equity stress; they are context for the thesis, not a signal.
An online refresh downloads to data/raw/credit/; offline builds only read the saved copies.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import requests

from . import data

SERIES = {
    "BAA10Y": "Moody's Baa corporate minus 10-year Treasury",
    "BAMLH0A0HYM2": "High-yield bonds (ICE BofA OAS)",
    "BAMLH0A3HYC": "CCC and lower (ICE BofA OAS)",
}
URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}"
HEADERS = {"User-Agent": "index-research-thesis/0.1 (personal research script)"}
FOLDER = Path("data/raw/credit")


def refresh(root: Path, get=requests.get) -> dict:
    """Download each series; keep the previous copy when a download fails or looks wrong."""
    folder = Path(root) / FOLDER
    folder.mkdir(parents=True, exist_ok=True)
    status = {}
    for series in SERIES:
        stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        try:
            response = get(URL.format(series=series), headers=HEADERS, timeout=60)
            response.raise_for_status()
            temp = folder / f"{series}.tmp"
            temp.write_text(response.text, encoding="utf-8")
            values = data.fred(temp)
            if len(values) < 250 or (values < -1).any() or (values > 50).any():
                temp.unlink(missing_ok=True)
                raise ValueError(f"unexpected series ({len(values)} observations)")
            temp.replace(folder / f"{series}.csv")
            status[series] = {"ok": True, "observed_at": stamp, "last": f"{values.index[-1]:%Y-%m-%d}"}
        except Exception as exc:
            status[series] = {"ok": False, "attempted_at": stamp, "error": str(exc)[:300]}
    (folder / "status.json").write_text(json.dumps(status, indent=2), encoding="utf-8")
    return status


def load(root: Path, now) -> dict:
    return {series: data.fred(Path(root) / FOLDER / f"{series}.csv", now) for series in SERIES}
