"""Scheduled intraday collection: option-chain window, waiting for builds/collections, summaries."""
import json, tempfile, unittest
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

import scheduled_collect as sc
from validation import NY

ROOT=Path(__file__).resolve().parents[1]
SCRATCH=ROOT/'work'/'scheduled_collect_tests'
SCRATCH.mkdir(parents=True,exist_ok=True)


def status(*items):return {'results':list(items)}


class ScheduledCollectTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=SCRATCH);self.root=Path(self.tmp.name);self.said=[];self.calls=[]
    def tearDown(self):self.tmp.cleanup()

    def collect(self,root,symbols,include_options):
        self.calls.append((list(symbols),include_options))
        return status(*({'symbol':s,'bar_status':'collected',**({'options_status':'indicative_only','option_contracts':10} if include_options else {})} for s in symbols))

    def go(self,when,busy=(),**kw):
        states=list(busy);slept=[]
        code=sc.run(self.root,now=lambda:pd.Timestamp(when,tz=NY),collect=self.collect,symbols=['SPY','QQQ'],
                    sleep=slept.append,say=self.said.append,lock_state=lambda r:{'busy':states.pop(0) if states else False},**kw)
        return code,slept

    def test_option_chains_only_while_the_market_is_open_on_trading_days(self):
        cases={'2026-11-09 15:50':True,'2026-11-09 16:00':False,'2026-11-09 20:10':False,
               '2026-11-26 15:50':False,'2026-11-07 15:50':False}  # Thanksgiving and a Saturday
        for when,expected in cases.items():
            self.assertEqual(sc.wants_options(pd.Timestamp(when,tz=NY)),expected,when)

    def test_afternoon_run_collects_bars_and_chains(self):
        code,_=self.go('2026-11-09 15:50')
        self.assertEqual((code,self.calls),(0,[(['SPY','QQQ'],True)]))
        self.assertIn('option chains for 2 of 2 (20 contracts)',self.said[-1])

    def test_evening_run_collects_bars_only(self):
        code,_=self.go('2026-11-09 20:10')
        self.assertEqual((code,self.calls),(0,[(['SPY','QQQ'],False)]))

    def test_waits_for_a_running_build(self):
        code,slept=self.go('2026-11-09 20:10',busy=[True,True,False])
        self.assertEqual((code,slept),(0,[15,15]))

    def test_waits_for_a_fresh_collection_but_not_a_stale_one(self):
        path=self.root/sc.STATUS;path.parent.mkdir(parents=True)
        path.write_text(json.dumps({'running':True,'started_at':'2026-11-10T01:05:00+00:00'}),encoding='utf-8')
        now=pd.Timestamp('2026-11-09 20:10',tz=NY)  # 5 minutes after that start
        self.assertTrue(sc.collection_running(self.root,now))
        self.assertFalse(sc.collection_running(self.root,now+pd.Timedelta(hours=1)))
        code,slept=self.go('2026-11-09 20:10',wait_limit=30)
        self.assertEqual((code,self.calls,len(slept)),(2,[],2))
        self.assertIn('Gave up',self.said[-1])

    def test_summary_exit_codes(self):
        ok={'symbol':'SPY','bar_status':'collected'}
        self.assertEqual(sc.summarize(status(ok))[0],0)
        self.assertEqual(sc.summarize(status(ok,{'symbol':'QQQ','bar_status':'failed'}))[0],1)
        self.assertEqual(sc.summarize(status({**ok,'options_status':'failed'}))[0],1)
        code,text=sc.summarize(status({'symbol':'SPY','bar_status':'failed'}))
        self.assertEqual(code,2);self.assertIn('not collected: SPY',text)


class BackupTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=SCRATCH);self.root=Path(self.tmp.name)
        for rel in ('data/intraday/v1/bars.jsonl','data/terminal/collection_status.json','data/monitor/paper_events.jsonl',
                    'data/raw/etfs.csv','data/intraday/v1/.writer.lock'):
            p=self.root/rel;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('x',encoding='utf-8')
    def tearDown(self):self.tmp.cleanup()

    def test_archive_has_collected_data_but_not_raw_caches_or_locks(self):
        import zipfile, data_backup
        cloud=self.root/'cloud'
        result=data_backup.run(self.root,say=lambda m:None,today=date(2026,11,9),cloud=cloud)
        for path in (result['local'],result['cloud']):
            with zipfile.ZipFile(path) as z:
                self.assertEqual(sorted(z.namelist()),['data/intraday/v1/bars.jsonl','data/monitor/paper_events.jsonl',
                                                       'data/terminal/collection_status.json'])
        self.assertTrue(result['cloud'].startswith(str(cloud)))

    def test_retention_keeps_recent_days_and_one_per_week(self):
        import data_backup
        folder=self.root/'b';folder.mkdir()
        for day in range(1,40):
            (folder/f'{data_backup.PREFIX}{date(2026,10,1)+timedelta(days=day)}.zip').write_text('z')
        data_backup.prune(folder,date(2026,11,9))
        kept=sorted(p.name[len(data_backup.PREFIX):-4] for p in folder.glob('*.zip'))
        self.assertEqual(kept,['2026-10-18','2026-10-25','2026-11-01','2026-11-07','2026-11-08','2026-11-09'])

    def test_no_cloud_folder_means_local_only(self):
        import data_backup
        said=[]
        result=data_backup.run(self.root,say=said.append,today=date(2026,11,9),cloud=None)
        self.assertIsNone(result['cloud']);self.assertIn('locally only',said[0])

    def test_evening_run_backs_up_and_afternoon_run_does_not(self):
        calls=[]
        for when in ('2026-11-09 20:10','2026-11-09 15:50'):
            sc.run(self.root,now=lambda w=when:pd.Timestamp(w,tz=NY),symbols=['SPY'],say=lambda m:None,
                   lock_state=lambda r:{'busy':False},backup=lambda root,say:calls.append(1),
                   collect=lambda root,symbols,include_options:status({'symbol':'SPY','bar_status':'collected'}))
        self.assertEqual(calls,[1])


if __name__=='__main__':unittest.main()
