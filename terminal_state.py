"""Read-only, versioned decision context joining current facts to frozen evidence.

This endpoint never trains, places orders, or creates forward paper observations.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from terminal_config import active_symbols, instrument, load_config
from intraday_collect import indicative_chain, utc
from validation import output_dir
import news_history


def clean(value):
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    if isinstance(value, (pd.Timestamp, Path)):
        return str(value)
    if isinstance(value, np.generic):
        return clean(value.item())
    if isinstance(value, float) and not np.isfinite(value):
        return None
    return value


def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8-sig'))
    except FileNotFoundError:
        return default


def _daily(root, symbol, now):
    path = output_dir(root) / 'daily_table.csv'
    if not path.exists():
        return {}, []
    data = pd.read_csv(path, parse_dates=['date'])
    date = now.tz_convert('America/New_York').tz_localize(None).normalize()
    # Today's completed/published close is never presumed available during trading.
    eligible = data[data['date'] < date] if now.tz_convert('America/New_York').hour < 20 else data[data['date'] <= date]
    if eligible.empty:
        return {}, []
    prefix = symbol.lower()
    if prefix + '_close' not in eligible:
        return {}, []
    valid = eligible[eligible[prefix + '_close'].notna()].tail(100)
    if valid.empty:
        return {}, []
    last = valid.iloc[-1]
    candles = []
    for _, row in valid.iterrows():
        values = {field: row.get(prefix + '_' + field) for field in ('open', 'high', 'low', 'close', 'volume')}
        if any(pd.isna(values[f]) for f in ('open', 'high', 'low', 'close')):
            continue
        candles.append({'time': str(row['date'].date()), **values})
    previous = valid.iloc[-2][prefix + '_close'] if len(valid) > 1 else None
    context = {'last_price': last[prefix + '_close'], 'last_daily_session': str(last['date'].date()),
               'change_pct': last[prefix + '_close'] / previous - 1 if previous else None,
               'vix': last.get('vix'), 'day_type': last.get('spy_day_type'),
               'source': 'Existing adjusted daily research table',
               'availability': 'legacy daily context; historical receipt times not archived',
               'execution_eligible': False}
    return clean(context), clean(candles)


def _events(root, now):
    path = root / 'data' / 'events' / 'events.csv'
    if not path.exists():
        return []
    data = pd.read_csv(path).fillna('')
    date = now.tz_convert('America/New_York').strftime('%Y-%m-%d')
    rows = data[(data['date'] >= date)].head(12)
    return [{'date': r.get('date'), 'time_et': r.get('time_et'), 'event': r.get('event'),
             'label': r.get('description') or r.get('event'),
             'verification': 'Configured calendar; initial schedule availability not archived',
             'signal_eligible': False} for r in rows.to_dict('records')]


def _indicative_summary(payload, now):
    if not payload:
        return None
    groups = {}
    current_date = now.tz_convert('America/New_York').strftime('%Y-%m-%d')
    age = (now - utc(payload['collected_at'])).total_seconds() / 60
    for row in payload.get('contracts', []):
        if row.get('expiry', '') < current_date:
            continue
        if row.get('strike') is None or not row.get('open_interest'):
            continue
        key = (row['expiry'], row['right'], row['strike'])
        groups[key] = groups.get(key, 0) + row['open_interest']
    levels = [{'id': 'indicative-' + '-'.join(map(str, key)), 'label': f'{key[1]} OI concentration ({key[0]})',
               'price': key[2], 'expiry': key[0], 'right': key[1], 'open_interest': count,
               'source': payload['source'], 'known_at': payload['collected_at'],
               'kind': 'unsigned_oi_concentration', 'execution_eligible': False,
               'age_minutes': age, 'expires_on': key[0],
               'status': 'indicative; OI date and same-day cutoff unverified'}
              for key, count in sorted(groups.items(), key=lambda item: item[1], reverse=True)[:12]]
    return {'status': 'indicative_only', 'as_of': payload['collected_at'],
            'age_minutes': age,
            'contracts': payload.get('contracts', []), 'levels': levels,
            'expiries': sorted({r['expiry'] for r in payload.get('contracts', [])}),
            'iv_context': {'status': 'provider indications; not calibrated probabilities'},
            'limitations': payload.get('limitations', [])}


def _journal(root, now):
    # Legacy log remains read-only; new module journal is joined if available.
    result = {'status': 'no_intraday_observations', 'decisions': 0, 'chain_verified': None, 'recent': [],
              'legacy': 'Existing daily paper experiment retained separately'}
    try:
        from intraday.paper import read_log
        path = root / 'data' / 'intraday' / 'v1' / 'paper.jsonl'
        if path.exists():
            rows = [r for r in read_log(root) if utc(r['recorded_at']) <= now]
            decisions = [r for r in rows if r.get('type') == 'decision']
            result.update(status='research_only', decisions=len(decisions), chain_verified=True,
                          recent=[r for r in rows if r.get('type') != 'experiment'][-10:])
    except ImportError:
        pass
    except (ValueError, OSError) as exc:
        result.update(status='integrity_error', chain_verified=False, reason=str(exc))
    return result


def price_levels(features):
    """Normalize native feature objects for the chart without inventing levels."""
    raw = features.get('levels', {})
    if isinstance(raw, list):
        return raw
    result = []
    orb = features.get('orb', {})
    for key, label in (('orb_high', 'Opening range high'), ('orb_low', 'Opening range low')):
        if raw.get(key) is not None:
            result.append({'id': key, 'label': label, 'price': raw[key], 'source': 'Observed 15-minute opening range',
                           'known_at': orb.get('available_at'), 'kind': 'opening_range'})
    prior = raw.get('prior_session') or {}
    for key, label in (('high', 'Previous session high'), ('low', 'Previous session low'), ('close', 'Previous session close')):
        if prior.get(key) is not None:
            result.append({'id': 'prior_' + key, 'label': label, 'price': prior[key], 'source': 'Complete previous session',
                           'known_at': prior.get('available_at'), 'kind': 'prior_session'})
    overnight = raw.get('overnight_observed') or {}
    for key in ('high', 'low'):
        if overnight.get(key) is not None:
            result.append({'id': 'overnight_' + key, 'label': 'Observed overnight ' + key,
                           'price': overnight[key], 'source': overnight.get('label'),
                           'known_at': features.get('as_of'), 'kind': 'partial_extended_hours'})
    return result


def build_state(root, symbol='SPY', as_of=None):
    root, now = Path(root), utc(as_of)
    item, config = instrument(root, symbol), load_config(root)
    symbol = item['symbol']
    errors, health = [], []
    context, daily_candles = _daily(root, symbol, now)
    chart = {'mode': 'daily', 'candles': daily_candles, 'vwap': [], 'levels': [],
             'limitation': 'Adjusted daily context is not an executable intraday chart'}
    features = None
    bars = []
    try:
        from intraday.store import load_bars
        from intraday.features import snapshot
        bars = load_bars(root, symbol, as_of=now.isoformat())
        if bars:
            features = snapshot(bars, now.isoformat())
            observed = features.get('bars', [])
            bounds = features.get('session', {})
            if bounds.get('open') and bounds.get('close'):
                regular = [r for r in observed if utc(bounds['open']) <= utc(r['timestamp']) and
                           utc(r['timestamp']) + pd.Timedelta(seconds=r.get('interval_seconds', 60)) <= utc(bounds['close'])]
            else:
                regular = []
            chart.update(mode='intraday', candles=regular or observed, extended_candles=observed,
                         vwap=features.get('vwap', []), levels=price_levels(features))
            chart['limitation'] = 'Archived bars; verify delay and availability basis before decisions'
    except (ImportError, ValueError, OSError, KeyError) as exc:
        errors.append('Intraday data: ' + str(exc))
    latest = max((utc(r['timestamp']) + pd.Timedelta(seconds=r.get('interval_seconds', 60)) for r in bars), default=None)
    age = (now - latest).total_seconds() if latest is not None else None
    bar_fresh = age is not None and 0 <= age <= config['collection']['quote_max_age_seconds']
    health.append({'name': 'Intraday prices', 'status': 'current_indicative' if bar_fresh else 'stale' if bars else 'unavailable',
                   'last': latest.isoformat() if latest is not None else None,
                   'reason': f'Latest bar age {age / 60:.1f} minutes; free archive has no executable bid/ask' if age is not None else 'Collect free bars or import timestamped observations'})
    health.append({'name': 'Daily research', 'status': 'context_only' if context else 'unavailable',
                   'last': context.get('last_daily_session'), 'reason': context.get('availability', 'No daily coverage for this instrument')})
    from liquidity_screen import evaluate
    from intraday.calendar import date_of, session
    liquidity_dates = sorted({date_of(r['timestamp']) for r in bars if session(date_of(r['timestamp'])).get('is_session')})
    if not liquidity_dates:
        liquidity_dates = [now.tz_convert('America/New_York').strftime('%Y-%m-%d')]
    try:
        liquidity = evaluate(root, symbol, liquidity_dates, config['liquidity'], now.isoformat(), execution='options')
        liquidity['share_only'] = evaluate(root, symbol, liquidity_dates, config['liquidity'], now.isoformat(), execution='shares')
    except (ValueError, OSError, KeyError) as exc:
        liquidity = {'status': 'data_blocked', 'research_eligible': False, 'reasons': [str(exc)]}
    health.append({'name': 'Research liquidity screen', 'status': liquidity.get('status', 'unavailable'),
                   'last': None, 'reason': '; '.join(liquidity.get('reasons', []))})
    try:  # the declared free policy, shown separately and never substituted for the verified screen
        liquidity['snapshot_policy'] = evaluate(root, symbol, liquidity_dates, config['liquidity'], now.isoformat(),
                                                execution='options', journal='snapshot')
        snap = liquidity['snapshot_policy']
        health.append({'name': 'Liquidity, free snapshot policy', 'status': snap.get('status', 'unavailable'),
                       'last': None, 'reason': 'Spreads are medians of a few intraday quote snapshots (liquidity_free.py), '
                       'not full-session medians. ' + '; '.join(snap.get('reasons', []))})
    except (ValueError, OSError, KeyError) as exc:
        health.append({'name': 'Liquidity, free snapshot policy', 'status': 'data_blocked', 'last': None, 'reason': str(exc)})
    if bars:
        context['intraday_last_price'] = bars[-1].get('close')
    if chart['mode'] == 'intraday' and chart['candles']:
        context['daily_last_price'] = context.get('last_price')
        context['daily_change_pct'] = context.get('change_pct')
        context['last_price'] = chart['candles'][-1]['close']
        prior = (features.get('levels', {}).get('prior_session') or {}).get('close')
        context['change_pct'] = context['last_price'] / prior - 1 if prior else None
        context['price_basis'] = 'Unadjusted displayed-session bar; change from the previous regular-session close'
        context['displayed_price_at'] = chart['candles'][-1].get('timestamp')
    options, option_records = None, []
    try:
        from options_research import load, summarize, select_expression
        option_records = load(root, symbol, as_of=now.isoformat())
        if option_records:
            options = summarize(option_records, spot=context.get('intraday_last_price') if bar_fresh else None, as_of=now.isoformat())
        option_expression = select_expression(option_records, 'flat', account=config['risk'], as_of=now.isoformat())
    except ImportError:
        option_expression = {'status': 'unavailable', 'reason': 'Contract-level quote adapter unavailable', 'sizing_allowed': False}
    except (ValueError, OSError, KeyError) as exc:
        errors.append('Options data: ' + str(exc))
        option_expression = {'status': 'data_blocked', 'reason': str(exc), 'sizing_allowed': False}
    indicative = _indicative_summary(indicative_chain(root, symbol, now), now)
    if options is None:
        options = indicative or {'status': 'unavailable', 'contracts': [], 'levels': [], 'expiries': [],
                                 'limitations': ['No contract-level dataset collected or imported.']}
    elif indicative:
        options['indicative_chain'] = indicative
    option_health = options.get('quote_health', {})
    option_age = option_health.get('latest_quote_age_seconds')
    health.append({'name': 'Options', 'status': 'stale_context' if option_age is not None and option_age > 60 else options.get('status', 'unavailable'),
                   'last': option_health.get('latest_quote_at') or options.get('as_of'),
                   'reason': '; '.join(options.get('limitations', [])) or 'Contract observations require quote-quality and account checks'})
    # Options-derived levels stay optional; default chart uses price-derived anchors only.
    chart['options_levels'] = [{**r, 'known_at': r.get('known_at') or r.get('knowledge_time'),
                                'kind': r.get('kind') or r.get('type')} for r in options.get('levels', [])]
    research = read_json(root / 'data' / 'intraday' / 'v1' / 'research' / (symbol + '.json'), {}) or {}
    if research.get('created_at') and utc(research['created_at']) > now:
        research = {}
    # Presentation adapter retains the saved experiment schema without rewriting its artifact.
    research['comparisons'] = [{**row,
        'name': row.get('name') or row.get('label') or f"{row.get('experiment', '?')} · {row.get('information', 'Unknown inputs')} → {row.get('execution', 'Unknown expression')}",
        'trades': research.get('metrics', {}).get('trades') if row.get('experiment') == 'A' else row.get('trades'),
        'mean_trade_return': research.get('metrics', {}).get('mean_trade_return') if row.get('experiment') == 'A' else row.get('mean_trade_return')}
        for row in research.get('comparisons', [])]
    if not research.get('created_at') and not research.get('metrics'):
        research = {}
    elif not research.get('liquidity', {}).get('research_eligible'):
        research['qualification_note'] = 'Prototype scenario predates the verified liquidity gate; it is not liquidity-qualified research.'
    evidence = {'status': 'insufficient_evidence', 'n_trades': research.get('metrics', {}).get('trades', 0),
                'n_sessions': research.get('metrics', {}).get('complete_sessions', 0),
                'net_expectancy': research.get('metrics', {}).get('mean_trade_return'),
                'uncertainty': research.get('uncertainty'),
                'limitations': ['Research scenarios are not a demonstrated forward edge.',
                                'No strategy is approved for personalized sizing.']}
    raw_signal = features.get('signal', {}) if features else {}
    if item.get('single_name'):
        raw_signal = {'reason': 'Separate single-name event study unavailable; index baseline signals are suppressed.'}
    side = raw_signal.get('side', 0)
    direction = 'long' if side in (1, 'long') else 'short' if side in (-1, 'short') else 'flat'
    flatten_by = None
    if features and features.get('session', {}).get('close'):
        from intraday.backtest import DEFAULT_CONFIG
        flatten_by = utc(features['session']['close']) - pd.Timedelta(minutes=DEFAULT_CONFIG['flatten_minutes_before_close'])
        if direction != 'flat' and now >= flatten_by:
            direction = 'flat'
            raw_signal = {'reason': 'Scheduled session flatten deadline reached; no new entry is eligible.'}
    reasons = ['No validated intraday strategy is approved for actionable sizing.']
    if any(config['risk'].get(k) is None for k in ('account_equity', 'max_loss_per_trade', 'max_daily_loss', 'shares_permission')):
        reasons.append('Required account risk limits or instrument permissions have not been configured.')
    if item.get('metadata_status') != 'issuer_verified':
        reasons.append('Configured product terms require dated issuer verification before qualification.')
    if not bar_fresh:
        reasons.append('Intraday observations are unavailable or stale.')
    if not option_records:
        reasons.append('Executable option quote history is unavailable; free-chain indications cannot certify fills.')
    if not liquidity.get('research_eligible'):
        reasons.append('The verified 20-session share/options liquidity screen has not qualified this research window.')
    if item.get('single_name'):
        reasons.append('Single-name leverage requires a separate event-driven study; the index baseline is blocked.')
    reasons.extend(errors)
    thesis = {'direction': direction, 'direction_basis': 'instrument_price', 'status': 'research_candidate' if direction != 'flat' else 'insufficient_evidence',
              'reason': raw_signal.get('reason') or 'Context available; no qualified intraday setup.',
              'trigger': raw_signal.get('entry_trigger'),
              'invalidation': raw_signal.get('invalidation') or (f"Observed invalidation level: {raw_signal['stop_level']:.4f}" if raw_signal.get('stop_level') is not None else None),
              'exit_rules': raw_signal.get('exit_rules') or ('Opposite range stop, 2R target, scheduled session flatten; research rules' if direction != 'flat' else None),
              'flatten_by': raw_signal.get('flatten_by'),
              'no_trade_reasons': reasons, 'sizing_allowed': False, 'actionable': False}
    if direction != 'flat' and flatten_by is not None:
        thesis['flatten_by'] = flatten_by.isoformat()
    if direction != 'flat' and option_records:
        from options_research import select_expression
        account = {**config['risk'], 'options_permitted': config['risk'].get('options_permission')}
        option_expression = select_expression(option_records, direction, account=account, as_of=now.isoformat())
    shares = {'status': 'research_only', 'instrument': symbol, 'direction': direction,
              'reason': 'Bar-price scenario only; risk limits and executable quotes are required.',
              'sizing_allowed': False, 'position_size': None}
    try:
        news = news_history.load(root, symbol, now.isoformat())
    except (ValueError, OSError, KeyError) as exc:
        news = []
        reasons.append('News history unavailable: ' + str(exc))
    collection = read_json(root / 'data' / 'terminal' / 'collection_status.json', {}) or {}
    if collection.get('started_at') and utc(collection['started_at']) > now:
        collection = {}
    market = features.get('market_session', {}) if features else {}
    if not market:
        from intraday.calendar import session
        market = session(now.tz_convert('America/New_York').strftime('%Y-%m-%d'))
    if not isinstance(market, dict):
        market = {'date': str(market)}
    market.update(timezone='America/New_York')
    market['status'] = ('closed' if not market.get('is_session') else
                        'pre_market' if now < utc(market['open']) else
                        'open' if now < utc(market['close']) else 'closed')
    capabilities = [
        {'name': 'Daily context', 'status': 'available' if context else 'unavailable', 'coverage': context.get('last_daily_session'), 'limitation': 'Existing daily dataset and research retained'},
        {'name': 'Intraday bars', 'status': 'available' if bars else 'unavailable', 'coverage': len(bars), 'limitation': 'Free archive; receipt time retained; bar-close availability is an explicit research assumption'},
        {'name': 'Options information', 'status': options.get('status'), 'coverage': len(options.get('contracts', [])) if isinstance(options.get('contracts'), list) else options.get('contracts'), 'limitation': 'Unsigned strike concentration is not observed dealer positioning'},
        {'name': 'Options execution', 'status': 'import_supported', 'coverage': len(option_records), 'limitation': 'Verified contract quote imports required; Yahoo indications are excluded'},
        {'name': 'News history', 'status': 'available' if news else 'unavailable', 'coverage': len(news), 'limitation': 'Only first-archived versions can appear in point-in-time replay'},
        {'name': 'Intraday validation', 'status': 'scenario_only' if research else 'not_run', 'coverage': evidence['n_trades'], 'limitation': 'No fabricated probabilities or forward results'},
        {'name': 'Research liquidity gate', 'status': liquidity.get('status', 'unavailable'), 'coverage': liquidity.get('eligible_fraction'), 'limitation': '20 prior verified sessions; at least 80% of the research window must pass; missing history fails closed'},
    ]
    state = {'schema_version': '1.0', 'as_of': now.isoformat(), 'symbol': symbol,
             'universe': active_symbols(root), 'instruments': config['universe'], 'instrument': item,
             'market': market, 'data_health': health, 'capabilities': capabilities,
             'context': context, 'chart': chart, 'options': options, 'news': news, 'liquidity': liquidity,
             'events': _events(root, now), 'thesis': thesis,
             'expressions': {'shares': shares, 'options': option_expression},
             'evidence': evidence, 'research': research, 'journal': _journal(root, now),
             'collection': collection, 'blockers': reasons,
             'execution_mode': 'decision_support_only',
             'links': {'quality': 'quality.html', 'research': 'backtests.html', 'paper': 'paper.html'}}
    state = clean(state)
    state['snapshot_id'] = hashlib.sha256(json.dumps(state, sort_keys=True, allow_nan=False).encode()).hexdigest()[:20]
    return state
