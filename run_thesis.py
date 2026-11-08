"""Build the Daily thesis tab from saved inputs; online builds first refresh credit spreads and earnings dates.

Never collects market data beyond those two downloads, never records a call and never places orders.
"""
import argparse
from pathlib import Path

from thesis.build import offline_requested, refresh_sources, render
from validation import output_dir


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--offline", action="store_true")
    args = ap.parse_args()
    root = Path(__file__).resolve().parent
    if not (args.offline or offline_requested()):
        refresh_sources(root, say=lambda m: print(m, flush=True))
    print(render(root, output_dir(root)), flush=True)
