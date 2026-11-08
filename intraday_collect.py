"""Explicit free-feed collection. Archive retrieval is never forward execution evidence."""
from __future__ import annotations

import hashlib
import json
import os
import threading
from pathlib import Path

import pandas as pd

from terminal_config import active_symbols, instrument, load_config

COLLECT_LOCK = threading.Lock()


def utc(value=None):
    t = pd.Timestamp(value) if value is not None else pd.Timestamp.now(tz='UTC')
    if t.tzinfo is None:
        raise ValueError('An explicit timezone is required')
    return t.tz_convert('UTC')


def write_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    candidate = path.with_suffix(path.suffix + '.tmp')
    candidate.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False), encoding='utf-8')
    os.replace(candidate, path)


def yahoo_bars(symbol):
    import yfinance as yf
    return yf.Ticker(symbol).history(period='5d', interval='1m', auto_adjust=False, prepost=True,
                                     actions=False, raise_errors=True)


def bar_records(symbol, frame, received_at):
    now = utc(received_at)
    if frame is None or frame.empty:
        raise ValueError('No intraday bars returned')
    if frame.index.tz is None:
        raise ValueError('Provider bar timestamps lack a timezone')
    result = []
    for at, row in frame.iterrows():
        start = utc(at)
        if start + pd.Timedelta(minutes=1) > now:
            continue  # never ingest an unfinished bar
        record = {'symbol': symbol, 'timestamp': start.isoformat(), 'available_at': now.isoformat(),
                  'recorded_at': now.isoformat(), 'interval_seconds': 60, 'source': 'Yahoo Finance / yfinance',
                  'availability_basis': 'retrieved_archive', 'adjusted': False}
        for field in ('open', 'high', 'low', 'close', 'volume'):
            value = float(row[field.title()])
            if not pd.notna(value) or value in (float('inf'), float('-inf')):
                raise ValueError('Provider returned nonfinite OHLCV')
            record[field] = value
        result.append(record)
    return result


def _number(value):
    try:
        x = float(value)
        return x if pd.notna(x) and abs(x) != float('inf') else None
    except (ValueError, TypeError):
        return None


def yahoo_chain(symbol, limit_expiries=3):
    """Indicative current chain only: Yahoo does not supply verified quote/OI publication times."""
    import yfinance as yf
    ticker = yf.Ticker(symbol)
    observed = []
    for expiry in list(ticker.options)[:limit_expiries]:
        chain = ticker.option_chain(expiry)
        for right, frame in (('call', chain.calls), ('put', chain.puts)):
            if frame is None:
                continue
            for _, row in frame.iterrows():
                trade_at = row.get('lastTradeDate')
                observed.append({'contract_id': str(row.get('contractSymbol') or ''), 'symbol': symbol,
                                 'expiry': expiry, 'right': right, 'strike': _number(row.get('strike')),
                                 'indicated_bid': _number(row.get('bid')), 'indicated_ask': _number(row.get('ask')),
                                 'volume': _number(row.get('volume')), 'open_interest': _number(row.get('openInterest')),
                                 'iv': _number(row.get('impliedVolatility')),
                                 'last_trade_at': str(trade_at) if pd.notna(trade_at) else None,
                                 'quote_time': None, 'open_interest_as_of': None,
                                 'execution_eligible': False})
    return observed


def refresh_headlines(root, symbols):
    """Reuse the existing headline adapters, but keep last-good caches on failure."""
    from tickers.news import _yahoo, _fed
    folder = Path(root) / 'data' / 'raw' / 'news'
    results = []
    for name, fetch in [(f'yahoo_{s}.json', lambda symbol=s: _yahoo(symbol)) for s in symbols] + [('fed_press.json', _fed)]:
        try:
            rows = fetch()
            if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
                raise ValueError('Headline adapter returned malformed observations')
            # Empty responses do not erase the last useful cache.
            if rows:
                write_json(folder / name, rows)
            results.append({'source': name, 'status': 'received' if rows else 'empty_retained', 'headlines': len(rows)})
        except Exception as exc:
            results.append({'source': name, 'status': 'failed_retained', 'error': str(exc)[:300]})
    return results


def collect(root, symbols=None, *, include_options=True, bars_for=None, chain_for=None, news_for=None, now=None):
    """Manual/background collector with failure retention; never places orders or writes paper outcomes."""
    from intraday.store import ingest_bars
    from news_history import archive_current
    if os.environ.get('APP_REPLAY') == '1' or os.environ.get('APP_OFFLINE') == '1':
        raise ValueError('Offline/replay mode cannot collect or write market observations')
    root = Path(root)
    cfg = load_config(root)
    symbols = symbols or cfg['collection']['default_symbols']
    if not isinstance(symbols, list) or not symbols or len(symbols) > len(active_symbols(root)):
        raise ValueError('Choose a nonempty list of configured symbols')
    symbols = list(dict.fromkeys(str(s).upper() for s in symbols))
    for symbol in symbols:
        if not instrument(root, symbol).get('active'):
            raise ValueError('Instrument is research-only and not enabled for intraday collection')
    if not COLLECT_LOCK.acquire(blocking=False):
        raise RuntimeError('An intraday collection is already running')
    status_path = root / 'data' / 'terminal' / 'collection_status.json'
    started = utc(now)
    status = {'version': 1, 'running': True, 'started_at': started.isoformat(), 'symbols': symbols,
              'provider': cfg['provider'], 'results': [], 'paper_records_created': 0}
    try:
        write_json(status_path, status)
        for symbol in symbols:
            item = {'symbol': symbol}
            try:
                frame = (bars_for or yahoo_bars)(symbol)
                receipt = utc(now) if now is not None else utc()
                records = bar_records(symbol, frame, receipt)
                item['bars'] = ingest_bars(root, records)
                item['bar_status'] = 'collected' if records else 'unavailable'
            except Exception as exc:
                item.update(bar_status='failed', bar_error=str(exc)[:500])
            if include_options:
                try:
                    chain = (chain_for or yahoo_chain)(symbol)
                    if not chain:
                        raise ValueError('No current option contracts returned; prior observations retained with their original age')
                    receipt = utc(now) if now is not None else utc()
                    payload = {'schema_version': 1, 'symbol': symbol, 'collected_at': receipt.isoformat(),
                               'source': 'Yahoo current chain / indicative', 'contracts': chain,
                               'quote_timestamp_verified': False, 'oi_date_verified': False,
                               'execution_eligible': False,
                               'limitations': ['Current chain only; no historical chain is reconstructed.',
                                               'Quote times and open-interest dates are not verified.',
                                               'Indicated prices cannot qualify executable options P&L.']}
                    # Keep every observation, then atomically update a convenience snapshot.
                    archive = root / 'data' / 'terminal' / 'free_options' / symbol
                    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]
                    write_json(archive / (receipt.strftime('%Y%m%dT%H%M%S') + '-' + digest + '.json'), payload)
                    write_json(archive / 'latest.json', payload)
                    item.update(options_status='indicative_only', option_contracts=len(chain))
                except Exception as exc:
                    item.update(options_status='failed', options_error=str(exc)[:500])
            status['results'].append(item)
            write_json(status_path, status)
        status['headline_refresh'] = (news_for or refresh_headlines)(root, symbols)
        status['news_archive'] = archive_current(root, utc(now) if now is not None else utc())
        status['ok'] = any(r.get('bar_status') == 'collected' for r in status['results'])
    finally:
        try:
            status.update(running=False, finished_at=utc(now).isoformat())
            write_json(status_path, status)
        finally:
            COLLECT_LOCK.release()
    return status


def indicative_chain(root, symbol, as_of):
    cutoff = utc(as_of)
    folder = Path(root) / 'data' / 'terminal' / 'free_options' / symbol
    paths = [folder / 'latest.json'] + sorted((p for p in folder.glob('*.json') if p.name != 'latest.json'), reverse=True)
    for path in paths:
        try:
            value = json.loads(path.read_text(encoding='utf-8'))
            if utc(value['collected_at']) <= cutoff:
                return value
        except (ValueError, KeyError, OSError):
            continue
    return None
