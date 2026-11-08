"""Build the Today workspace from available saved inputs; never collects or submits orders."""
import argparse
from pathlib import Path

from today.build import build
from validation import output_dir


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--offline', action='store_true')
    ap.parse_args()
    root = Path(__file__).resolve().parent
    print(build(root, output_dir(root)), flush=True)
