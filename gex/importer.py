"""Copy a GEX/DIX CSV you downloaded from SqueezeMetrics into the app (data/manual/DIX.csv).

Looks in your Downloads folder for the newest file named like DIX*.csv (browsers save repeats as
"DIX (1).csv", and so on), checks it, and only replaces your copy if it's newer. The old copy is
kept as data/manual/DIX_previous.csv. Nothing here contacts SqueezeMetrics.
"""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd

from .data import DIX_FILE, _day, load_dix


def default_downloads() -> Path:
    env = os.environ.get("HUB_DOWNLOADS")
    return Path(env) if env else Path.home() / "Downloads"


def find_latest(folder: Path) -> Path | None:
    if not folder.is_dir():
        return None
    files = [p for p in folder.iterdir() if p.is_file() and p.name.lower().startswith("dix") and p.suffix.lower() == ".csv"]
    return max(files, key=lambda p: p.stat().st_mtime) if files else None


def import_latest(folder: Path | None = None) -> dict:
    folder = Path(folder) if folder else default_downloads()
    f = find_latest(folder)
    if f is None:
        return {"ok": False, "error": f"No DIX CSV found in {folder}. Click 'Get the file', then CSV on their page, then Update."}
    try:
        new = load_dix(f)
    except Exception as e:  # a half-finished download or a different file
        return {"ok": False, "error": f"Couldn't read {f.name}: {e}"}
    if new is None or len(new) < 250 or not {"dix", "gex"} <= set(new.columns):
        return {"ok": False, "error": f"{f.name} doesn't look like SqueezeMetrics' DIX/GEX file (needs date, dix and gex columns)."}
    cur = load_dix()
    if cur is not None and len(cur) and new.index.max() <= cur.index.max():
        same = new.index.max() == cur.index.max()
        return {"ok": False, "error": (f"Your copy already runs through {_day(cur.index.max())}; {f.name} isn't newer. "
                                       + ("SqueezeMetrics may not have posted today's value yet." if same else "Download a fresh copy first."))}
    DIX_FILE.parent.mkdir(parents=True, exist_ok=True)
    if DIX_FILE.exists():
        DIX_FILE.replace(DIX_FILE.with_name("DIX_previous.csv"))
    out = new.reset_index()
    out["date"] = out["date"].dt.strftime("%Y-%m-%d")
    out.to_csv(DIX_FILE, index=False, lineterminator="\n")
    return {"ok": True, "file": f.name, "through": f"{new.index.max():%Y-%m-%d}",
            "message": f"Imported {f.name}: your copy now runs through {_day(new.index.max())} ({len(new):,} days)."}
