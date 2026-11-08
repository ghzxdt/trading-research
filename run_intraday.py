"""Intraday collection, imports, research scenarios and read-only replay."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

import pandas as pd

from intraday_collect import collect, utc, write_json
from terminal_config import active_symbols, instrument, load_config
from terminal_state import build_state, clean

ROOT = Path(__file__).resolve().parent


def records_from(path):
    path = Path(path)
    if path.suffix.lower() == '.csv':
        frame = pd.read_csv(path).astype(object)
        return frame.where(pd.notna(frame), None).to_dict('records')
    if path.suffix.lower() == '.jsonl':
        return [json.loads(line) for line in path.read_text(encoding='utf-8-sig').splitlines() if line.strip()]
    value = json.loads(path.read_text(encoding='utf-8-sig'))
    return value if isinstance(value, list) else value.get('records', [])


def research(root, symbol, *, assume_bar_close_availability=False, config=None, liquidity_journal='verified'):
    from intraday.store import load_bars
    from intraday.backtest import run, configuration
    root = Path(root)
    if os.environ.get('APP_REPLAY') == '1' or os.environ.get('APP_OFFLINE') == '1':
        raise ValueError('Replay/offline rebuilds cannot publish new research artifacts')
    item = instrument(root, symbol)
    if item.get('single_name'):
        raise ValueError('Single-name leverage requires a separately registered event-driven study; index baseline parameters cannot be shared.')
    bars = load_bars(root, symbol, as_of=utc().isoformat())
    if not bars:
        raise ValueError('No intraday bars exist. Collect or import observations first.')
    from liquidity_screen import evaluate
    from intraday.calendar import date_of, session
    dates = sorted({date_of(r['timestamp']) for r in bars if session(date_of(r['timestamp'])).get('is_session')})
    liquidity = evaluate(root, symbol, dates, load_config(root)['liquidity'], utc().isoformat(), execution='options',
                         journal=liquidity_journal)
    if not liquidity['research_eligible']:
        raise ValueError('Liquidity screen blocked signal research: ' + '; '.join(liquidity.get('reasons', [])))
    original_dataset_hash = hashlib.sha256(json.dumps(bars, sort_keys=True).encode()).hexdigest()
    eligible_dates = {row['session_date'] for row in liquidity['session_results'] if row['research_eligible']}
    bars = [row for row in bars if date_of(row['timestamp']) in eligible_dates]
    config = configuration({**(config or {}), 'assume_bar_close_availability': bool(assume_bar_close_availability)})
    folder = root / 'data' / 'intraday' / 'v1' / 'research'
    registry = folder / 'trial_registry.jsonl'
    old = [json.loads(line) for line in registry.read_text(encoding='utf-8').splitlines() if line.strip()] if registry.exists() else []
    policy = liquidity['thresholds'] if liquidity_journal == 'verified' else {**liquidity['thresholds'], 'journal': liquidity_journal}
    variant = hashlib.sha256(json.dumps({'symbol': symbol, 'config': config, 'liquidity_policy': policy}, sort_keys=True).encode()).hexdigest()
    variants = {r['variant_hash'] for r in old}
    if variant not in variants and len(variants) >= 32:
        raise ValueError('The declared 32-variant research budget is exhausted; create a reviewed study version')
    variants.add(variant)
    report = clean(run(bars, config))
    report['study'].update(registered_variants=len(variants), search_family='All registered symbol/config variants', max_variants=32)
    report['holding_model'] = {'holding_scope': 'same_session', 'leveraged_return_basis': 'observed_instrument_prices',
                               'additional_decay_adjustment': 0, 'break_even_holding_period': None,
                               'break_even_reason': 'Not identifiable from realized volatility alone'}
    report.update(created_at=utc().isoformat(), symbol=symbol, status='historical_scenario', evidence_status='historical_scenario',
                  forward_validated=False, sizing_allowed=False, liquidity=liquidity)
    report['dataset_hash'] = hashlib.sha256(json.dumps(bars, sort_keys=True).encode()).hexdigest()
    report['pre_screen_dataset_hash'] = original_dataset_hash
    report['comparisons'] = [
        {'experiment': 'A', 'information': 'Price/volume', 'execution': 'Shares', 'status': 'historical scenario'},
        {'experiment': 'B', 'information': 'Price/volume + options', 'execution': 'Shares', 'status': 'requires timestamped options feature history'},
        {'experiment': 'C', 'information': 'Price/volume', 'execution': 'Options', 'status': 'requires executable contract history'},
        {'experiment': 'D', 'information': 'Price/volume + options', 'execution': 'Options', 'status': 'requires timestamped features and contract history'},
    ]
    run_id = hashlib.sha256(json.dumps(report, sort_keys=True).encode()).hexdigest()[:20]
    report['research_run_id'] = run_id
    write_json(folder / 'runs' / (run_id + '.json'), report)
    write_json(folder / (symbol + '.json'), report)
    registry.parent.mkdir(parents=True, exist_ok=True)
    with registry.open('a', encoding='utf-8') as stream:
        stream.write(json.dumps({'run_id': run_id, 'variant_hash': variant, 'symbol': symbol, 'created_at': report['created_at'],
                                 'config': report.get('config', config), 'dataset_hash': report['dataset_hash'],
                                 'evidence_status': report['evidence_status']}, sort_keys=True) + '\n')
    return report


def paper_observation(root, symbol):
    from intraday.store import load_bars
    from intraday.features import snapshot
    from intraday.paper import record_decision
    from liquidity_screen import evaluate
    if instrument(root, symbol).get('single_name'):
        raise ValueError('Single-name observations require a separate event-driven study; index journal parameters cannot be shared.')
    now = utc()
    observed = snapshot(load_bars(root, symbol, as_of=now.isoformat()), now.isoformat())
    gate = evaluate(root, symbol, [now.tz_convert('America/New_York').strftime('%Y-%m-%d')],
                    load_config(root)['liquidity'], now.isoformat(), execution='options')
    observed['quality']['liquidity'] = gate
    if not gate['research_eligible']:
        observed['quality']['forward_eligible'] = False
        observed['quality']['reasons'].append('Verified liquidity prerequisite has not passed.')
    return record_decision(root, observed, now=now.isoformat(), qualification_policy={
        'thresholds': gate['thresholds'], 'window_sessions': gate['window_sessions'], 'required_fraction': gate['required_fraction']})


def parser():
    ap = argparse.ArgumentParser(description=__doc__)
    commands = ap.add_subparsers(dest='command', required=True)
    c = commands.add_parser('collect', help='Explicitly collect free indicative data; no orders/paper fills')
    c.add_argument('--symbols', nargs='+')
    c.add_argument('--all', action='store_true', help='Collect all configured active symbols; more requests')
    c.add_argument('--without-options', action='store_true')
    for command in ('status', 'replay', 'research', 'paper-record'):
        p = commands.add_parser(command)
        p.add_argument('--symbol', default='SPY')
        if command == 'replay':
            p.add_argument('--as-of', required=True, help='Timezone-qualified knowledge cutoff')
        if command == 'research':
            p.add_argument('--assume-bar-close-availability', action='store_true',
                           help='Explicit historical timing scenario; never forward evidence')
            p.add_argument('--liquidity-journal', choices=['verified', 'snapshot'], default='verified',
                           help='snapshot = the declared free policy (spreads from a few intraday snapshots); '
                                'results are labeled and counted as separate variants')
    for command in ('import-bars', 'import-options', 'import-liquidity'):
        p = commands.add_parser(command)
        p.add_argument('path', help='JSON/JSONL/CSV with explicit timestamps and provenance')
    return ap


def main(argv=None, root=ROOT):
    ap = parser()
    args = ap.parse_args(argv)
    root = Path(root)
    try:
        if args.command == 'collect':
            result = collect(root, active_symbols(root) if args.all else args.symbols, include_options=not args.without_options)
        elif args.command == 'import-bars':
            from intraday.store import ingest_bars
            result = ingest_bars(root, records_from(args.path))
        elif args.command == 'import-options':
            from options_research import ingest
            result = ingest(root, records_from(args.path))
        elif args.command == 'import-liquidity':
            from liquidity_screen import import_verified
            result = import_verified(root, records_from(args.path))
        elif args.command == 'research':
            result = research(root, args.symbol.upper(), assume_bar_close_availability=args.assume_bar_close_availability,
                              liquidity_journal=args.liquidity_journal)
        elif args.command == 'paper-record':
            result = paper_observation(root, args.symbol.upper())
        else:
            result = build_state(root, args.symbol.upper(), getattr(args, 'as_of', None))
    except (ValueError, OSError, RuntimeError) as exc:
        ap.error(str(exc))
    print(json.dumps(clean(result), indent=2, sort_keys=True, allow_nan=False))
    return result


if __name__ == '__main__':
    main()
