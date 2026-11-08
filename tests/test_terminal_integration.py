"""Behavioral checks for point-in-time terminal composition and explicit collection."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

import intraday_collect as collector
import news_history
import terminal_config
from terminal_api import handle_get
from terminal_state import build_state
from terminal_state import _indicative_summary

SCRATCH = Path(__file__).resolve().parents[1] / 'work' / 'terminal_tests'
SCRATCH.mkdir(parents=True, exist_ok=True)


class TerminalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=SCRATCH)
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def daily(self):
        (self.root / 'output').mkdir()
        pd.DataFrame([
            {'date': '2026-11-05', 'spy_open': 100, 'spy_high': 102, 'spy_low': 99,
             'spy_close': 101, 'spy_volume': 1000, 'vix': 20},
            {'date': '2026-11-06', 'spy_open': 101, 'spy_high': 104, 'spy_low': 100,
             'spy_close': 103, 'spy_volume': 1100, 'vix': 19},
        ]).to_csv(self.root / 'output' / 'daily_table.csv', index=False)

    def test_shared_universe_contains_all_confirmed_instruments(self):
        symbols = terminal_config.active_symbols(self.root)
        self.assertEqual(len(symbols), 16)
        self.assertTrue({'SOXL', 'TNA', 'LABD', 'KORU', 'BITX', 'ERY', 'FNGU', 'UPRO', 'SPXL', 'NVDL', 'TSLL'} <= set(symbols))
        self.assertEqual(terminal_config.instrument(self.root, 'FNGU')['product_type'], 'ETN')
        self.assertTrue(terminal_config.instrument(self.root, 'TSLL')['single_name'])

    def test_missing_inputs_are_readonly_and_never_recommend_a_position(self):
        state = build_state(self.root, 'SOXL', '2026-11-07T18:00:00Z')
        self.assertFalse(state['thesis']['actionable'])
        self.assertIsNone(state['expressions']['shares']['position_size'])
        self.assertEqual(state['expressions']['options']['status'], 'no_trade')
        self.assertEqual(state['research'], {})
        self.assertEqual(next(c['status'] for c in state['capabilities'] if c['name'] == 'Intraday validation'), 'not_run')
        self.assertFalse((self.root / 'data').exists())
        json.dumps(state, allow_nan=False)

    def test_daily_close_is_not_available_during_the_same_session(self):
        self.daily()
        state = build_state(self.root, 'SPY', '2026-11-06T15:00:00Z')
        self.assertEqual(state['context']['last_daily_session'], '2026-11-05')
        self.assertEqual(state['context']['last_price'], 101)

    def test_news_is_first_seen_not_backdated_to_publication(self):
        cache = self.root / 'data' / 'raw' / 'news'
        cache.mkdir(parents=True)
        (cache / 'yahoo_SPY.json').write_text(json.dumps([{'title': 'Earlier headline', 'url': 'https://example.com/a',
                                                        'time': '2026-11-06T12:00:00Z'}]))
        result = news_history.archive_current(self.root, '2026-11-07T12:00:00Z')
        self.assertEqual(result['added'], 1)
        self.assertEqual(news_history.load(self.root, 'SPY', '2026-11-06T18:00:00Z'), [])
        self.assertEqual(len(news_history.load(self.root, 'SPY', '2026-11-07T13:00:00Z')), 1)
        self.assertEqual(news_history.archive_current(self.root, '2026-11-07T14:00:00Z')['added'], 0)

    def test_offline_collect_never_calls_network_or_writes(self):
        with patch.dict(os.environ, {'APP_OFFLINE': '1'}), patch.object(collector, 'yahoo_bars') as fetch:
            with self.assertRaises(ValueError):
                collector.collect(self.root)
            fetch.assert_not_called()
        self.assertFalse((self.root / 'data').exists())

    def test_collector_releases_lock_when_status_writes_fail(self):
        with patch.object(collector, 'write_json', side_effect=OSError('disk unavailable')):
            with self.assertRaises(OSError):
                collector.collect(self.root, ['SPY'])
        self.assertFalse(collector.COLLECT_LOCK.locked())

    def test_free_feed_receipts_do_not_claim_historical_availability(self):
        frame = pd.DataFrame({'Open': [100], 'High': [102], 'Low': [99], 'Close': [101], 'Volume': [10]},
                             index=pd.DatetimeIndex(['2026-11-06T14:30:00Z']))
        rows = collector.bar_records('SPY', frame, '2026-11-07T12:00:00Z')
        self.assertEqual(rows[0]['available_at'], '2026-11-07T12:00:00+00:00')
        self.assertEqual(rows[0]['availability_basis'], 'retrieved_archive')

    def test_unfinished_bars_are_not_ingested(self):
        frame = pd.DataFrame({'Open': [100], 'High': [102], 'Low': [99], 'Close': [101], 'Volume': [10]},
                             index=pd.DatetimeIndex(['2026-11-06T14:30:00Z']))
        self.assertEqual(collector.bar_records('SPY', frame, '2026-11-06T14:30:30Z'), [])

    def test_api_rejects_unconfigured_symbol_and_ambiguous_cutoff(self):
        self.assertEqual(handle_get(self.root, '/api/v1/thesis_state', {'symbol': ['../../secret']})[0], 400)
        self.assertEqual(handle_get(self.root, '/api/v1/thesis_state', {'as_of': ['a', 'b']})[0], 400)
        self.assertEqual(handle_get(self.root, '/api/v1/missing', {})[0], 404)

    def test_risk_config_rejects_infinite_limits(self):
        config = terminal_config.defaults()
        config['risk']['max_daily_loss'] = float('inf')
        (self.root / 'terminal_config.json').write_text(json.dumps(config))
        with self.assertRaises(ValueError):
            terminal_config.load_config(self.root)

    def test_expired_indicative_levels_disappear_without_rewriting_archive(self):
        payload = {'collected_at': '2026-11-06T15:00:00Z', 'source': 'test indicative source',
                   'contracts': [{'expiry': '2026-11-06', 'right': 'call', 'strike': 100, 'open_interest': 12}],
                   'limitations': ['Timestamp unverified']}
        before = _indicative_summary(payload, collector.utc('2026-11-06T16:00:00Z'))
        after = _indicative_summary(payload, collector.utc('2026-11-09T15:00:00Z'))
        self.assertEqual(len(before['levels']), 1)
        self.assertEqual(after['levels'], [])
        self.assertEqual(len(payload['contracts']), 1)

    def test_indicative_replay_never_uses_a_future_latest_snapshot(self):
        folder = self.root / 'data' / 'terminal' / 'free_options' / 'SPY'
        folder.mkdir(parents=True)
        old = {'collected_at': '2026-11-06T15:00:00Z', 'contracts': [{'id': 'old'}]}
        future = {'collected_at': '2026-11-09T15:00:00Z', 'contracts': [{'id': 'future'}]}
        (folder / '20261106T150000-a.json').write_text(json.dumps(old))
        (folder / '20261109T150000-a.json').write_text(json.dumps(future))
        (folder / 'latest.json').write_text(json.dumps(future))
        result = collector.indicative_chain(self.root, 'SPY', '2026-11-07T15:00:00Z')
        self.assertEqual(result['contracts'][0]['id'], 'old')

    def test_collector_empty_chain_retains_prior_snapshot(self):
        folder = self.root / 'data' / 'terminal' / 'free_options' / 'SPY'
        folder.mkdir(parents=True)
        original = json.dumps({'collected_at': '2026-11-06T15:00:00Z', 'contracts': [{'id': 'retained'}]})
        (folder / 'latest.json').write_text(original)
        frame = pd.DataFrame({'Open': [100], 'High': [102], 'Low': [99], 'Close': [101], 'Volume': [10]},
                             index=pd.DatetimeIndex(['2026-11-06T14:30:00Z']))
        result = collector.collect(self.root, ['SPY'], bars_for=lambda s: frame, chain_for=lambda s: [],
                                   news_for=lambda root, symbols: [], now='2026-11-07T12:00:00Z')
        self.assertEqual(result['results'][0]['options_status'], 'failed')
        self.assertEqual((folder / 'latest.json').read_text(), original)

    def test_candidate_is_suppressed_at_flatten_deadline_including_early_close(self):
        for close in ('2026-11-06T21:00:00Z', '2026-11-27T18:00:00Z'):
            deadline = collector.utc(close) - pd.Timedelta(minutes=5)
            features = {'bars': [], 'session': {'close': close}, 'signal': {'side': 1, 'entry_trigger': 101}}
            with patch('intraday.store.load_bars', return_value=[{'timestamp': (deadline - pd.Timedelta(minutes=1)).isoformat(), 'close': 101}]), patch('intraday.features.snapshot', return_value=features):
                before = build_state(self.root, 'SPY', (deadline - pd.Timedelta(seconds=1)).isoformat())
                at = build_state(self.root, 'SPY', deadline.isoformat())
                after = build_state(self.root, 'SPY', (deadline + pd.Timedelta(minutes=1)).isoformat())
            self.assertEqual(before['thesis']['direction'], 'long')
            self.assertEqual(before['thesis']['flatten_by'], deadline.isoformat())
            for state in (at, after):
                self.assertEqual(state['thesis']['direction'], 'flat')
                self.assertIsNone(state['thesis']['trigger'])
                self.assertIsNone(state['thesis']['flatten_by'])
                self.assertEqual(state['expressions']['shares']['direction'], 'flat')
                self.assertEqual(state['expressions']['options']['status'], 'no_trade')

    def test_research_comparisons_have_readable_names_and_actual_baseline_metrics(self):
        folder = self.root / 'data' / 'intraday' / 'v1' / 'research'
        folder.mkdir(parents=True)
        saved = {'created_at': '2026-11-06T20:00:00Z', 'metrics': {'trades': 5, 'mean_trade_return': .01},
                 'comparisons': [{'experiment': 'A', 'information': 'Price/volume', 'execution': 'Shares', 'status': 'scenario'},
                                 {'experiment': 'B', 'information': 'Options features', 'execution': 'Shares', 'status': 'unavailable'}]}
        (folder / 'SPY.json').write_text(json.dumps(saved))
        state = build_state(self.root, 'SPY', '2026-11-07T18:00:00Z')
        a, b = state['research']['comparisons']
        self.assertIn('Price/volume', a['name'])
        self.assertEqual(a['trades'], 5)
        self.assertEqual(a['mean_trade_return'], .01)
        self.assertIsNone(b['trades'])
        self.assertEqual(json.loads((folder / 'SPY.json').read_text()), saved)
        self.assertIn('predates', state['research']['qualification_note'])

    def test_research_liquidity_and_single_name_gates_run_before_signal_testing(self):
        from run_intraday import research
        with patch.dict(os.environ, {'APP_OFFLINE': '0', 'APP_REPLAY': '0'}), patch('intraday.backtest.run') as engine:
            with self.assertRaisesRegex(ValueError, 'Single-name'):
                research(self.root, 'NVDL')
            with patch('intraday.store.load_bars', return_value=[{'timestamp': '2026-11-06T14:30:00Z', 'close': 100}]):
                with self.assertRaisesRegex(ValueError, 'Liquidity screen blocked'):
                    research(self.root, 'SPY', assume_bar_close_availability=True)
            engine.assert_not_called()
        self.assertFalse((self.root / 'data' / 'intraday' / 'v1' / 'research').exists())

    def test_single_name_view_suppresses_index_candidate(self):
        features = {'bars': [], 'session': {'close': '2026-11-06T21:00:00Z'}, 'signal': {'side': 1}}
        with patch('intraday.store.load_bars', return_value=[{'timestamp': '2026-11-06T14:45:00Z', 'close': 100}]), patch('intraday.features.snapshot', return_value=features):
            state = build_state(self.root, 'TSLL', '2026-11-06T14:46:00Z')
        self.assertEqual(state['thesis']['direction'], 'flat')
        self.assertEqual(state['instrument']['research_track'], 'single_name_event')
        self.assertEqual(state['expressions']['options']['status'], 'no_trade')

    def test_observation_cannot_be_forward_eligible_without_liquidity_history(self):
        from run_intraday import paper_observation
        from intraday.paper import read_log
        now = collector.utc('2026-11-06T17:00:00Z')
        observed = {'symbol': 'SPY', 'snapshot_id': 'test-observed-live', 'as_of': now.isoformat(),
                    'session': {'date': '2026-11-06'}, 'signal': {'state': 'candidate', 'side': 1},
                    'quality': {'forward_eligible': True, 'availability_bases': ['observed_live'], 'reasons': []}}
        with patch('run_intraday.utc', return_value=now), patch('intraday.store.load_bars', return_value=[]), patch('intraday.features.snapshot', return_value=observed):
            result = paper_observation(self.root, 'SPY')
        self.assertEqual(result['state'], 'data_blocked')
        self.assertFalse(result['event']['quality']['forward_eligible'])
        experiment = next(row for row in read_log(self.root) if row['type'] == 'experiment')
        self.assertEqual(experiment['spec']['qualification_policy']['window_sessions'], 20)


if __name__ == '__main__':
    unittest.main()
