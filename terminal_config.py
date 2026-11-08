"""Versioned terminal settings and shared instrument universe.

Configuration establishes research scope, never execution eligibility.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

SCHEMA_VERSION = 1
ACTIVE = ['SPY', 'QQQ', 'IWM', 'TQQQ', 'SQQQ', 'SOXL', 'TNA', 'LABD',
          'KORU', 'BITX', 'ERY', 'FNGU', 'UPRO', 'SPXL', 'NVDL', 'TSLL']
INSTRUMENTS = [
    ('SPY', 'S&P 500', 1, 'ETF', 'SPY', False),
    ('QQQ', 'Nasdaq-100', 1, 'ETF', 'QQQ', False),
    ('IWM', 'Russell 2000', 1, 'ETF', 'IWM', False),
    ('TQQQ', 'Nasdaq-100', 3, 'ETF', 'QQQ', False),
    ('SQQQ', 'Nasdaq-100', -3, 'ETF', 'QQQ', False),
    ('SOXL', 'Semiconductors', 3, 'ETF', 'SOXL', False),
    ('TNA', 'Russell 2000', 3, 'ETF', 'IWM', False),
    ('LABD', 'Biotechnology', -3, 'ETF', 'LABD', False),
    ('KORU', 'South Korean equities', 3, 'ETF', 'KORU', False),
    ('BITX', 'Bitcoin-linked futures', 2, 'ETF', 'BITX', False),
    ('ERY', 'Energy equities', -2, 'ETF', 'ERY', False),
    ('FNGU', 'FANG+ equities', 3, 'ETN', 'FNGU', False),
    ('UPRO', 'S&P 500', 3, 'ETF', 'SPY', False),
    ('SPXL', 'S&P 500', 3, 'ETF', 'SPY', False),
    ('NVDL', 'NVDA', 2, 'ETF', 'NVDL', True),
    ('TSLL', 'TSLA', 2, 'ETF', 'TSLL', True),
    ('DIA', 'Dow industrials', 1, 'ETF', 'DIA', False),
    ('RSP', 'Equal-weight S&P 500', 1, 'ETF', 'RSP', False),
    ('SPXU', 'S&P 500', -3, 'ETF', 'SPY', False),
]


def defaults():
    return {
        'schema_version': SCHEMA_VERSION,
        'universe': [{'symbol': s, 'exposure_group': g, 'configured_leverage': l,
                      'product_type': p, 'signal_market': m, 'single_name': n,
                      'active': s in ACTIVE, 'research_only': s not in ACTIVE,
                      'metadata_status': 'configured; dated issuer verification required before qualification'}
                     for s, g, l, p, m, n in INSTRUMENTS],
        'provider': 'yahoo_free_indicative',
        'collection': {'period': '5d', 'interval': '1m', 'quote_max_age_seconds': 120,
                       'default_symbols': ['SPY', 'QQQ', 'IWM'], 'auto_collect': False},
        'liquidity': {'min_share_volume': 1000000, 'max_share_spread_bps': 10,
                      'min_options_volume': 10000, 'max_options_spread_bps': 100},
        'risk': {'account_equity': None, 'max_trade_debit': None,
                 'max_loss_per_trade': None, 'max_daily_loss': None,
                 'options_permission': None, 'shares_permission': None},
        'execution': {'mode': 'research_and_paper', 'order_submission': False},
        'research': {'strategy': 'orb-continuation-v1', 'auto_optimize': False,
                     'approved_strategies': []},
    }


def load_config(root):
    path = Path(root) / 'terminal_config.json'
    base = defaults()
    if path.exists():
        raw = json.loads(path.read_text(encoding='utf-8-sig'))
        if raw.get('schema_version') != SCHEMA_VERSION:
            raise ValueError('Unsupported terminal configuration version')
        for key, value in raw.items():
            if key in ('collection', 'liquidity', 'risk', 'execution', 'research'):
                base[key].update(value)
            else:
                base[key] = value
    symbols = []
    for item in base['universe']:
        symbol = item.get('symbol', '')
        if not symbol or not symbol.isascii() or not symbol.replace('-', '').isalnum() or len(symbol) > 12:
            raise ValueError('Invalid configured instrument symbol')
        if symbol in symbols:
            raise ValueError('Duplicate instrument in terminal universe')
        symbols.append(symbol)
        item['research_track'] = 'single_name_event' if item.get('single_name') else 'index_or_sector'
        item['liquidity_tier'] = 3 if item.get('single_name') else 1 if symbol in ACTIVE[:6] else 2
    for name, value in base['liquidity'].items():
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            raise ValueError(f'Liquidity threshold {name} must be positive and finite')
    for name, value in base['risk'].items():
        if name not in ('options_permission', 'shares_permission') and value is not None:
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                raise ValueError(f'{name} must be positive or unavailable')
    if base['execution'].get('order_submission'):
        raise ValueError('This terminal has no order-submission capability')
    return base


def active_symbols(root):
    return [r['symbol'] for r in load_config(root)['universe'] if r.get('active')]


def instrument(root, symbol):
    symbol = str(symbol).upper()
    for row in load_config(root)['universe']:
        if row['symbol'] == symbol:
            return row
    raise ValueError('Instrument is outside the configured research universe')
