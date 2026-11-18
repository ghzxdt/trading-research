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


class CboeConnectionTests(unittest.TestCase):
    def test_a_dropped_idle_connection_is_retried_on_a_fresh_one(self):
        """The 2026-11-17 failure: the server closes a kept-alive connection, and the next GET on it gets nothing."""
        import socket, threading
        listener=socket.socket();listener.bind(('127.0.0.1',0));listener.listen(5)
        port=listener.getsockname()[1];body=b'DATE,CLOSE\n11/16/2026,20.1\n'
        reply=b'HTTP/1.1 200 OK\r\nContent-Length: %d\r\nConnection: keep-alive\r\n\r\n%s'%(len(body),body)
        def handle(conn):
            with conn:
                conn.recv(65536);conn.sendall(reply)  # answer the first request on this connection...
                conn.recv(65536)                       # ...then drop the second one without a reply
        def serve():
            while True:
                try:conn,_addr=listener.accept()
                except OSError:return
                threading.Thread(target=handle,args=(conn,),daemon=True).start()
        threading.Thread(target=serve,daemon=True).start()
        try:
            session=guard.make_session();url=f'http://127.0.0.1:{port}/VIX_History.csv'
            self.assertEqual(guard.newest_csv_date(session.get(url,timeout=5).text),date(2026,11,16))
            self.assertEqual(guard.newest_csv_date(session.get(url,timeout=5).text),date(2026,11,16))  # retried
            plain=__import__('requests').Session()
            plain.get(url,timeout=5)
            with self.assertRaises(Exception):plain.get(url,timeout=5)  # what the old shared session did
        finally:listener.close()

    def test_data_only_message_names_the_reason(self):
        self.assertIn("hasn't posted",guard.data_only_message("Cboe hasn't posted the VIX close for Tue Nov 17 yet"))
        self.assertIn("couldn't be checked",guard.data_only_message("Couldn't check whether Cboe has posted"))


class CommandLineTests(unittest.TestCase):
    def test_run_all_refuses_an_online_refresh_the_guard_blocks(self):
        import run_all
        with patch.object(sys,'argv',['run_all.py']),patch('refresh_guard.blocking_reason',return_value='Cboe has not posted'),\
             patch.object(run_all,'build') as build:
            with self.assertRaises(SystemExit) as stop:run_all.main()
        self.assertIn('Cboe has not posted',str(stop.exception));self.assertIn('--data-only',str(stop.exception))
        build.assert_not_called()

    def test_data_only_skips_the_guard_and_records_nothing(self):
        import run_all
        with patch.object(sys,'argv',['run_all.py','--data-only']),patch('refresh_guard.blocking_reason',return_value='blocked') as check,             patch.object(run_all,'ROOT',SCRATCH),patch.object(run_all,'build',return_value=SCRATCH) as build,patch('builtins.print'):
            run_all.main()
        check.assert_not_called()
        self.assertEqual(build.call_args.kwargs,{'offline':False,'as_of':None,'record':False})

    def test_offline_and_override_skip_the_guard(self):
        import run_all
        for argv in (['run_all.py','--offline'],['run_all.py','--skip-vix-guard']):
            with patch.object(sys,'argv',argv),patch('refresh_guard.blocking_reason',return_value='blocked') as check,\
                 patch.object(run_all,'ROOT',SCRATCH),patch.object(run_all,'build',return_value=SCRATCH) as build,\
                 patch('builtins.print'):
                run_all.main()
            check.assert_not_called();build.assert_called_once()


if __name__=='__main__':unittest.main()
