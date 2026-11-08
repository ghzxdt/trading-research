"""Small versioned localhost API; network collection and research are explicit actions."""
from __future__ import annotations

import json
import threading
from pathlib import Path

from intraday_collect import collect, utc
from terminal_config import active_symbols, instrument
from terminal_state import build_state, clean, read_json


def handle_get(root, route, query):
    root = Path(root)
    try:
        if route == '/api/v1/thesis_state':
            symbols = query.get('symbol', ['SPY'])
            if len(symbols) != 1:
                raise ValueError('Choose one symbol')
            symbol = str(symbols[0]).upper()
            cutoff = query.get('as_of', [None])
            if len(cutoff) != 1:
                raise ValueError('Choose one replay cutoff')
            if cutoff[0] and utc(cutoff[0]) > utc():
                raise ValueError('A replay cutoff cannot be in the future')
            return 200, build_state(root, symbol, cutoff[0])
        if route == '/api/v1/thesis/calls':
            import pandas as pd
            from thesis import calls, data
            return 200, calls.summary(root, data.etfs(root, pd.Timestamp.now(tz='America/New_York')))
        if route == '/api/v1/universe':
            return 200, {'schema_version': 1, 'universe': active_symbols(root)}
        if route == '/api/v1/intraday/status':
            return 200, read_json(root / 'data' / 'terminal' / 'collection_status.json', {'running': False, 'status': 'not_collected'})
        return 404, {'ok': False, 'error': 'Unknown terminal endpoint'}
    except (ValueError, TypeError, OSError, KeyError) as exc:
        return 400, {'ok': False, 'error': str(exc)}


def start_action(root, route, payload, update_state, on_finished):
    root = Path(root)
    routes = {'/api/v1/intraday/collect', '/api/v1/intraday/research', '/api/v1/intraday/paper'}
    if route not in routes:
        raise ValueError('Unknown terminal action')
    symbol = str(payload.get('symbol', 'SPY')).upper()
    instrument(root, symbol)
    symbols = payload.get('symbols', [symbol])
    if not isinstance(symbols, list) or not symbols or len(symbols) > len(active_symbols(root)):
        raise ValueError('Choose configured symbols')
    for value in symbols:
        if not isinstance(value, str) or value.upper() not in active_symbols(root):
            raise ValueError('Collection symbol is not active in the terminal universe')
    for key in ('options', 'assume_bar_close_availability'):
        if key in payload and not isinstance(payload[key], bool):
            raise ValueError(key + ' must be boolean')
    from intraday.store import readonly
    if readonly():
        raise ValueError('Offline/replay mode is read-only')
    started = utc().isoformat()
    action = route.rsplit('/', 1)[-1]
    update_state(running=True, ok=None, action='intraday_' + action, started_at=started,
                 finished_at=None, message='Running ' + action + ' for ' + symbol + '...')

    def work():
        try:
            if action == 'collect':
                result = collect(root, [s.upper() for s in symbols], include_options=payload.get('options', True))
                message = 'Collection finished. Today shows received data and provider limitations.'
                ok = bool(result.get('ok'))
            elif action == 'research':
                from run_intraday import research
                result = research(root, symbol, assume_bar_close_availability=payload.get('assume_bar_close_availability', False))
                message = f"Research scenario saved: {result.get('metrics', {}).get('trades', 0)} trades. This is not forward evidence."
                ok = True
            else:
                from run_intraday import paper_observation
                result = paper_observation(root, symbol)
                message = 'Research observation: ' + str(result.get('state')) + '. No orders submitted.'
                ok = bool(result.get('recorded')) or result.get('state') == 'duplicate'
            update_state(running=False, ok=ok, finished_at=utc().isoformat(), message=message,
                         terminal_result=clean(result))
        except Exception as exc:
            update_state(running=False, ok=False, finished_at=utc().isoformat(), message=action + ' failed: ' + str(exc)[:700])
        finally:
            on_finished()

    threading.Thread(target=work, name='terminal-' + action, daemon=True).start()
    return 202, {'ok': True, 'running': True, 'action': action, 'symbol': symbol, 'started_at': started}
