"""Build original-vs-fixed, cost backtests, paper, quality and employment tabs."""
import argparse
from pathlib import Path
from validation import output_dir
from monitor.build import build

if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--offline',action='store_true');ap.add_argument('--refresh-jobs',action='store_true')
    args=ap.parse_args()
    if args.offline and args.refresh_jobs:ap.error('Offline builds cannot refresh network sources')
    root=Path(__file__).resolve().parent
    print(build(root,output_dir(root),refresh_jobs=args.refresh_jobs),flush=True)
