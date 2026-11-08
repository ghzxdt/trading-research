"""The VIX guard: an online refresh must not log a session as data_blocked before Cboe posts its VIX close."""
import json, sys, tempfile, unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pandas as pd

import refresh_guard as guard
from monitor import paper
from validation import NY

ROOT=Path(__file__).resolve().parents[1]
SCRATCH=ROOT/'work'/'refresh_guard_tests'
SCRATCH.mkdir(parents=True,exist_ok=True)
MONDAY_EVENING=pd.Timestamp('2026-11-09 17:00',tz=NY)


class BlockingReasonTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=SCRATCH);self.root=Path(self.tmp.name)
        (self.root/'data/monitor').mkdir(parents=True)
        (self.root/'data/monitor/experiment_lock.json').write_text(json.dumps({'version':'v1','strategies':[{'id':'a'},{'id':'b'}]}),encoding='utf-8')
        self.log=self.root/'data/monitor/paper_events.jsonl';self.events=[]
    def tearDown(self):self.tmp.cleanup()

    def record(self,day):
        for rule in ('a','b'):paper.append(self.log,self.events,{'type':'decision','key':f'v1:{day}:{rule}','state':'recorded_before_entry'})

    def reason(self,now=MONDAY_EVENING,vix=date(2026,11,6)):
        def vix_date():
            if isinstance(vix,Exception):raise vix
            return vix
        return guard.blocking_reason(self.root,now=now,vix_date=vix_date)

    def test_blocks_after_4_30_until_cboe_posts_the_vix_close(self):
        text=self.reason()
        self.assertIn("Cboe hasn't posted the VIX close for Mon Nov 9",text);self.assertIn('ends Nov 6',text)
        self.assertIsNone(self.reason(vix=date(2026,11,9)))

    def test_already_logged_session_is_never_blocked(self):
        self.record('2026-11-09')
        self.assertIsNone(self.reason())

    def test_before_4_30_the_previous_session_is_the_one_that_counts(self):
        self.record('2026-11-06')
        self.assertIsNone(self.reason(now=pd.Timestamp('2026-11-09 16:10',tz=NY)))

    def test_after_the_next_open_it_is_too_late_to_matter(self):
        self.assertIsNone(self.reason(now=pd.Timestamp('2026-11-10 10:00',tz=NY)))

    def test_unreachable_cboe_blocks_with_its_own_reason(self):
        self.assertIn("Couldn't check",self.reason(vix=OSError('offline')))

    def test_missing_experiment_still_checks_vix(self):
        (self.root/'data/monitor/experiment_lock.json').unlink()
        self.assertIn("hasn't posted",self.reason())

    def test_entry_time_skips_weekends(self):
        self.assertEqual(guard.entry_time(pd.Timestamp('2026-11-06')),pd.Timestamp('2026-11-09 09:30',tz=NY))


class CommandLineTests(unittest.TestCase):
    def test_run_all_refuses_an_online_refresh_the_guard_blocks(self):
        import run_all
        with patch.object(sys,'argv',['run_all.py']),patch('refresh_guard.blocking_reason',return_value='Cboe has not posted'),\
             patch.object(run_all,'build') as build:
            with self.assertRaises(SystemExit) as stop:run_all.main()
        self.assertIn('Cboe has not posted',str(stop.exception));build.assert_not_called()

    def test_offline_and_override_skip_the_guard(self):
        import run_all
        for argv in (['run_all.py','--offline'],['run_all.py','--skip-vix-guard']):
            with patch.object(sys,'argv',argv),patch('refresh_guard.blocking_reason',return_value='blocked') as check,\
                 patch.object(run_all,'ROOT',SCRATCH),patch.object(run_all,'build',return_value=SCRATCH) as build,\
                 patch('builtins.print'):
                run_all.main()
            check.assert_not_called();build.assert_called_once()


if __name__=='__main__':unittest.main()
