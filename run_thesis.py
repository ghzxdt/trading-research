"""Build the Daily thesis tab from saved inputs.

Online builds first refresh credit spreads and earnings dates, and afterwards append the page's own stance for
the latest close to data/thesis/stance_log.jsonl (forward only; see thesis/stance_log.py). Offline and replay
builds only read. Never records a user call and never places orders.
"""
import argparse
from pathlib import Path

from thesis.build import build_state, log_stance, offline_requested, refresh_sources, render
from validation import now_et, output_dir


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--offline", action="store_true")
    args = ap.parse_args()
    root = Path(__file__).resolve().parent
    online = not (args.offline or offline_requested())
    say = lambda m: print(m, flush=True)  # noqa: E731
    if online:
        refresh_sources(root, say=say)
    now = now_et()
    state = build_state(root, now)
    if online:
        log_stance(root, state, now, say=say)
    print(render(root, output_dir(root), state), flush=True)
