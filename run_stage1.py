"""Stage 1: download free market history, build the daily table, run the seven studies, write the report.

Usage:
    python run_stage1.py            # download fresh data, then build everything
    python run_stage1.py --offline  # reuse the last download (no internet needed)
    python run_stage1.py --open     # also open the report in your browser when done
    python run_stage1.py --check    # run the self-check (no look-ahead, arithmetic, labels) and stop
"""

from __future__ import annotations

import argparse
import json
import sys
import warnings
import webbrowser
from pathlib import Path

from stage1 import dataset, health, report, selfcheck, sources, studies
from validation import FLOAT_FORMAT, freshness, output_dir, validate_daily_table, write_component_manifest

ROOT = Path(__file__).resolve().parent
OUT = output_dir(ROOT)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--offline", action="store_true", help="use the cached data in data/raw instead of downloading")
    ap.add_argument("--open", action="store_true", help="open the report in your browser when done")
    ap.add_argument("--check", action="store_true", help="run the self-check and stop (no report)")
    args = ap.parse_args()

    warnings.simplefilter("ignore", category=FutureWarning)
    warnings.filterwarnings("ignore", message=".*DataFrame is highly fragmented.*")

    raw = sources.fetch_all(offline=args.offline)
    print("Building the daily table...")
    table, dictionary = dataset.build(raw)
    long = dataset.build_long(raw)

    validate_daily_table(table)
    print("Running the temporal-prefix, arithmetic and label gates...")
    gates = selfcheck.run(raw, table)
    for ok, msg in gates:
        print(f"  {'PASS' if ok else 'FAIL'}  {msg}")
    failed = sum(1 for ok, _ in gates if not ok)
    if failed:
        raise RuntimeError(f"{failed} validation gate(s) failed; no report published.")
    if args.check:
        print("All checks passed. Prefix invariance does not establish historical data availability.")
        return

    OUT.mkdir(exist_ok=True)
    table.to_csv(OUT / "daily_table.csv", float_format=FLOAT_FORMAT)
    dictionary.to_csv(OUT / "data_dictionary.csv", index=False)
    long.to_csv(OUT / "long_history.csv", float_format=FLOAT_FORMAT)
    fresh = {tk: freshness(table[f"{tk.lower()}_close"].last_valid_index()) for tk in sources.ETFS}
    fresh.update({name.upper(): freshness(raw["vol"][name].last_valid_index()) for name in ("vix", "vix9d", "vix3m", "vvix")})
    fresh.update({name.upper(): freshness(raw["rates"][name].last_valid_index(), kind="rates") for name in ("dgs2", "dgs10")})
    (OUT / "source_freshness.json").write_text(json.dumps(fresh, indent=2, sort_keys=True), encoding="utf-8")
    (OUT / "validation_report.json").write_text(json.dumps({"passed": True, "checks": [{"passed": bool(ok), "message": msg} for ok, msg in gates]}, indent=2), encoding="utf-8")

    print("Checking the data...")
    checks = health.check(raw, table, raw.get("status"), long)
    for item in checks["items"]:
        if item["level"] == "warn":
            print(f"  WARNING  {item['check']}: {item['result']}")

    print("Running the seven studies...")
    results, tests_run = studies.run_all(table, long)
    path = report.build(results, tests_run, table, OUT / "report.html", checks)
    write_component_manifest("indexes", OUT, {"offline": args.offline, "market_through": str(table.index[-1].date()), "tests_run": tests_run, "gates_passed": True})

    try:  # the GEX / DIX tab's Cold/Warm/Hot indicator uses this fresh VIX
        from gex import data as gex_data
        g = gex_data.write_status(table, OUT)
        print(f"  GEX / DIX tab: {g['label']}")
    except Exception as e:  # never let the optional tab break this one
        print(f"  (GEX / DIX indicator not updated: {e})")

    sm = checks["summary"]
    print()
    print(f"Done. {len(table):,} trading days, {table.index[0]:%Y-%m-%d} to {table.index[-1]:%Y-%m-%d}.")
    print(f"  Data check:      {sm['warn']} warning(s), {sm['note']} note(s), {sm['ok']} OK")
    print(f"  Report:          {path}")
    print(f"  Daily table:     {OUT / 'daily_table.csv'}")
    print(f"  Long history:    {OUT / 'long_history.csv'} (SPY from {long.index[0]:%Y}, for risk numbers)")
    print(f"  What each column means: {OUT / 'data_dictionary.csv'}")
    if args.open:
        webbrowser.open(path.as_uri())


if __name__ == "__main__":
    main()
