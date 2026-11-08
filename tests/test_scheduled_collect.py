"""Scheduled intraday collection: option-chain window, waiting for builds/collections, summaries."""
import json, tempfile, unittest
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


if __name__=='__main__':unittest.main()
