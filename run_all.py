"""Refresh the whole hub: Indexes (run_stage1.py), Tickers (run_tickers.py), Leverage (run_leverage.py), then GEX / DIX (run_gex.py).

GEX / DIX is rebuilt from your saved copy; it never downloads anything (use its Update button for that).

Usage:
    python run_all.py            # fresh data for both tabs
    python run_all.py --offline  # reuse the last downloads
    python run_all.py --open     # open the hub when done
"""

from __future__ import annotations

import argparse
import os
import webbrowser
from pathlib import Path

from build_pipeline import build

ROOT = Path(__file__).resolve().parent


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--offline", action="store_true", help="reuse the last downloads")
    ap.add_argument("--open", action="store_true", help="open the hub when done")
    ap.add_argument("--as-of", help="ISO reference timestamp; combine with --offline for reproducible replay")
    args = ap.parse_args()
    lock = ROOT / ".build.lock"
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as e:
        raise RuntimeError("A build lock exists. If no build is running, remove .build.lock and retry; interrupted publication is recovered automatically.") from e
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(str(os.getpid()))
        out = build(ROOT, offline=args.offline, as_of=args.as_of)
    finally:
        lock.unlink(missing_ok=True)
    hub = out / "index.html"
    print(f"Published complete validated bundle: {hub}")
    if args.open:
        webbrowser.open(hub.as_uri())


if __name__ == "__main__":
    main()
