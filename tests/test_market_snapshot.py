"""Twice-daily market snapshots: slot windows, futures, the inflation nowcast, file writing, independent
failures and the build wait. (Kalshi collection was removed on 2026-11-19; the user dropped perp tracking.)"""
import csv, tempfile, unittest
from datetime import date
from pathlib import Path

import pandas as pd

import market_snapshot as ms
from validation import NY

ROOT=Path(__file__).resolve().parents[1]
SCRATCH=ROOT/'work'/'market_snapshot_tests'
SCRATCH.mkdir(parents=True,exist_ok=True)
STAMP=pd.Timestamp('2026-11-09 16:05',tz=NY)
MORNING=pd.Timestamp('2026-11-09 09:00',tz=NY)
NOWCAST=[{'chart':{'subcaption':'2026-10','_comment':'2026-11-06 00:00'},  # fewer points than labels
          'categories':[{'category':[{'label':'11/03'},{'label':'11/04'},{'label':'11/05'},{'label':'11/06'}]}],
          'dataset':[{'seriesname':'CPI Inflation','data':[{'value':'0.24','tooltext':'CPI Inflation{br}11/05{br}0.24'},
                                                           {'value':'0.2421','tooltext':'CPI Inflation{br}11/06{br}0.2421'}]}]},
         {'chart':{'subcaption':'2026-11','_comment':'2026-11-06 00:00'},
          'categories':[{'category':[{'label':'11/02'},{'label':'11/06'}]}],
          'dataset':[{'seriesname':'CPI Inflation','data':[{'value':'0.18'},{'value':''}]},
                     {'seriesname':'Actual CPI Inflation','data':[{'value':''},{'value':''}]}]},
         {'chart':{'subcaption':'2026-12','_comment':'2027-01-04 00:00'},
          'categories':[{'category':[{'label':'12/30'},{'label':'01/04'}]}],
          'dataset':[{'seriesname':'Core CPI Inflation','data':[{'value':'0.2'},{'value':'0.25'}]}]}]


def bars(*points):
    return pd.DataFrame({'Close':[p for _,p in points]},index=pd.DatetimeIndex([pd.Timestamp(t,tz=NY) for t,_ in points]))


FRIDAY_TO_MONDAY=bars(('2026-11-06 15:58',7400.0),('2026-11-06 15:59',7402.0),('2026-11-06 16:00',7403.0),
                      ('2026-11-09 08:49',7420.0),('2026-11-09 08:50',7424.0))


class SlotTests(unittest.TestCase):
    def test_slot_windows(self):
        cases={'08:00':'morning','09:29':'morning','09:30':'manual','12:00':'manual','16:00':'close','16:45':'close','16:46':'manual'}
        for clock,slot in cases.items():
            self.assertEqual(ms.slot_for(pd.Timestamp(f'2026-11-09 {clock}',tz=NY)),slot,clock)

class FuturesAndNowcastTests(unittest.TestCase):
    def test_last_close_time_skips_weekends_and_holidays(self):
        cases=[('2026-11-09 09:00','2026-11-06 16:00'),('2026-11-09 16:05','2026-11-09 16:00'),('2026-11-26 09:00','2026-11-25 16:00')]
        for now,close in cases:
            self.assertEqual(ms.last_close_time(pd.Timestamp(now,tz=NY)),pd.Timestamp(close,tz=NY),now)

    def test_futures_row_measures_the_move_since_the_last_close(self):
        row=ms.futures_row('ES=F',FRIDAY_TO_MONDAY,MORNING,'morning')
        self.assertEqual((row['last_price'],row['ref_4pm_price'],row['delay_min']),(7424.0,7402.0,10.0))
        self.assertEqual(row['ref_4pm_bar_et'],'2026-11-06T15:59:00-05:00')
        self.assertAlmostEqual(row['change_since_4pm_pct'],(7424/7402-1)*100,places=4)
        self.assertIsNone(ms.futures_row('ES=F',pd.DataFrame({'Close':[]}),MORNING,'morning'))

    def test_nowcast_rows_take_the_latest_value_and_roll_the_year(self):
        rows=ms.nowcast_rows(NOWCAST,STAMP,'close')
        self.assertEqual([(r['target_month'],r['series'],r['value_mom_pct'],r['as_of']) for r in rows],
                         [('2026-10','CPI Inflation',0.2421,'2026-11-06'),  # dated by tooltip, not position
                          ('2026-11','CPI Inflation',0.18,'2026-11-02'),('2026-12','Core CPI Inflation',0.25,'2027-01-04')])


class SnapshotRunTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=SCRATCH);self.root=Path(self.tmp.name);self.said=[];self.slept=[]
    def tearDown(self):self.tmp.cleanup()

    def go(self,when=STAMP,busy=(),scheduled=True,bars_for=lambda s:FRIDAY_TO_MONDAY,nowcast=lambda:NOWCAST,network=None):
        states=list(busy)
        lock=lambda root:{'busy':states.pop(0) if states else False}
        return ms.run(self.root,scheduled=scheduled,bars_for=bars_for,nowcast=nowcast,now=lambda:when,
                      sleep=self.slept.append,say=self.said.append,lock_state=lock,network=network)

    def test_waits_for_the_network_only_when_it_will_download(self):
        order=[]
        def bars_for(symbol):
            order.append('download');return FRIDAY_TO_MONDAY
        self.assertEqual(self.go(bars_for=bars_for,network=lambda:order.append('network')),0)
        self.assertEqual(order[0],'network')
        skipped=[]
        self.go(when=pd.Timestamp('2026-11-09 12:00',tz=NY),network=lambda:skipped.append(1))
        self.assertEqual(skipped,[])

    def rows(self,name):
        path=self.root/name
        if not path.exists():return []
        with path.open(encoding='utf-8') as f:return list(csv.DictReader(f))

    def test_close_snapshot_writes_both_files_with_one_header(self):
        self.assertEqual(self.go(),0);self.assertEqual(self.go(),0)
        counts=[len(self.rows(f)) for f in (ms.FUTURES_FILE,ms.NOWCAST_FILE)]
        self.assertEqual(counts,[2*len(ms.FUTURES),6])
        self.assertEqual({r['slot'] for r in self.rows(ms.FUTURES_FILE)},{'close'})
        self.assertEqual((self.root/ms.FUTURES_FILE).read_text(encoding='utf-8').count('snapshot_utc'),1)
        self.assertFalse((self.root/'data'/'kalshi').exists())  # no Kalshi collection any more

    def test_morning_snapshot_skips_the_nowcast(self):
        self.assertEqual(self.go(when=MORNING),0)
        self.assertEqual(self.rows(ms.NOWCAST_FILE),[])
        self.assertEqual(self.rows(ms.FUTURES_FILE)[0]['change_since_4pm_pct'],str(round((7424/7402-1)*100,4)))

    def test_waits_for_a_running_build_before_writing(self):
        self.assertEqual(self.go(busy=[True,True,False]),0)
        self.assertEqual(self.slept,[15,15]);self.assertTrue(any('waited 30s' in s for s in self.said))

    def test_scheduled_run_outside_windows_writes_nothing(self):
        self.assertEqual(self.go(when=pd.Timestamp('2026-11-09 12:00',tz=NY)),0)
        self.assertFalse((self.root/ms.FUTURES_FILE).exists())

    def test_each_source_fails_on_its_own(self):
        def no_nowcast():raise OSError('offline')
        self.assertEqual(self.go(nowcast=no_nowcast),1)
        self.assertEqual(len(self.rows(ms.FUTURES_FILE)),len(ms.FUTURES))
        self.assertTrue(any('nowcast: offline' in s for s in self.said))
        def no_futures(symbol):raise RuntimeError('503')
        self.assertEqual(self.go(bars_for=no_futures),1)  # the nowcast still records
        self.assertEqual(len(self.rows(ms.NOWCAST_FILE)),3)


if __name__=='__main__':unittest.main()
