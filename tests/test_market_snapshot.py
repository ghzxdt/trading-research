"""Twice-daily market snapshots: slot windows, Kalshi quote/depth math, futures, the inflation
nowcast, file writing, independent failures and the build wait."""
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
MARKET={'ticker':'KXUS500PERP','status':'active','schedule':{'is_open':True},'bid':'13.0000','ask':'13.0010',
        'bid_size_fp':'50.00','ask_size_fp':'40.00','price':'13.0005','liquidation_mark_price':{'price':'13.0004'},
        'reference_price':{'price':'12.9900','ts_ms':1794000000000},'open_interest':'1000.00',
        'open_interest_notional_value_dollars':'13000.00','volume_24h':'500.00','volume_24h_notional_value_dollars':'6500.00'}
BOOK={'bids':[['12.9000','10.00'],['12.9800','10.00'],['12.9990','30.00'],['13.0000','50.00']],
      'asks':[['13.1000','5.00'],['13.0020','20.00'],['13.0010','40.00']]}
ESTIMATE={'funding_rate':0.0001,'next_funding_time':'2026-11-09T21:00:00Z'}
CPI={'ticker':'KXCPI-26OCT-T0.3','event_ticker':'KXCPI-26OCT','yes_sub_title':'Above 0.3%','floor_strike':0.3,
     'strike_type':'greater','status':'active','close_time':'2026-11-10T13:29:00Z','yes_bid_dollars':'0.4100',
     'yes_ask_dollars':'0.4300','yes_bid_size_fp':'100.00','yes_ask_size_fp':'80.00','last_price_dollars':'0.4200',
     'volume_24h_fp':'1500.00','volume_fp':'9000.00','open_interest_fp':'7000.00'}
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


def fake_get(path,params=None):
    if path=='/margin/markets':return {'markets':[dict(MARKET,ticker=t) for t in ms.INDEX_PERPS]}
    if path.endswith('/orderbook'):return {'orderbook':BOOK}
    if path=='/margin/funding_rates/estimate':return ESTIMATE
    if path=='/markets':return {'markets':[CPI] if params['series_ticker']=='KXCPI' else []}
    raise AssertionError(path)


class KalshiRowTests(unittest.TestCase):
    def test_slot_windows(self):
        cases={'08:00':'morning','09:29':'morning','09:30':'manual','12:00':'manual','16:00':'close','16:45':'close','16:46':'manual'}
        for clock,slot in cases.items():
            self.assertEqual(ms.slot_for(pd.Timestamp(f'2026-11-09 {clock}',tz=NY)),slot,clock)

    def test_perp_row_quotes_premium_and_depth(self):
        row=ms.perp_row(MARKET,BOOK,ESTIMATE,STAMP,'close')
        self.assertAlmostEqual(row['mid'],13.0005)
        self.assertAlmostEqual(row['spread_bp'],0.001/13.0005*1e4,places=3)
        self.assertAlmostEqual(row['premium_bp'],(13.0005/12.99-1)*1e4,places=3)
        self.assertAlmostEqual(row['bid_depth_5bp_usd'],12.999*30+13.0*50,places=2)   # 12.98 is 15 bp away
        self.assertAlmostEqual(row['bid_depth_25bp_usd'],12.98*10+12.999*30+13.0*50,places=2)
        self.assertAlmostEqual(row['ask_depth_25bp_usd'],13.002*20+13.001*40,places=2)  # 13.10 is 73 bp away
        self.assertEqual((row['book_levels'],row['funding_rate_estimate'],row['is_open']),(7,0.0001,True))
        self.assertEqual(row['reference_utc'],pd.Timestamp(1794000000000,unit='ms',tz='UTC').isoformat())
        self.assertEqual(row['snapshot_et'],'2026-11-09T16:05:00-05:00')

    def test_missing_book_or_side_leaves_values_blank(self):
        row=ms.perp_row(MARKET,None,None,STAMP,'close')
        self.assertIsNone(row['bid_depth_5bp_usd']);self.assertIsNone(row['book_levels'])
        closed=ms.perp_row(dict(MARKET,ask=None,schedule={'is_open':False}),{'bids':BOOK['bids'],'asks':[]},None,STAMP,'manual')
        self.assertEqual((closed['mid'],closed['spread_bp'],closed['is_open']),(None,None,False))

    def test_no_quote_placeholder_is_treated_as_missing(self):
        placeholder='922337203685477.5807'  # what Kalshi sends for an empty side
        row=ms.perp_row(dict(MARKET,ask=placeholder),{'bids':BOOK['bids'],'asks':[[placeholder,'1.00']]},
                        {'funding_rate':0,'next_funding_time':'0001-01-01T00:00:00Z'},STAMP,'close')
        self.assertEqual((row['ask'],row['mid'],row['spread_bp'],row['premium_bp']),(None,None,None,None))
        self.assertEqual((row['book_levels'],row['next_funding_utc']),(4,None))

    def test_event_rows(self):
        [row]=ms.event_rows([CPI],'KXCPI',STAMP,'close')
        self.assertEqual((row['outcome'],row['yes_bid'],row['yes_ask'],row['open_interest']),('Above 0.3%',0.41,0.43,7000.0))


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

    def go(self,get=fake_get,when=STAMP,busy=(),scheduled=True,bars_for=lambda s:FRIDAY_TO_MONDAY,nowcast=lambda:NOWCAST):
        states=list(busy)
        lock=lambda root:{'busy':states.pop(0) if states else False}
        return ms.run(self.root,scheduled=scheduled,get=get,bars_for=bars_for,nowcast=nowcast,now=lambda:when,
                      sleep=self.slept.append,say=self.said.append,lock_state=lock)

    def rows(self,name):
        path=self.root/name
        if not path.exists():return []
        with path.open(encoding='utf-8') as f:return list(csv.DictReader(f))

    def test_close_snapshot_writes_all_four_files_with_one_header(self):
        self.assertEqual(self.go(),0);self.assertEqual(self.go(),0)
        counts=[len(self.rows(f)) for f in (ms.PERP_FILE,ms.EVENT_FILE,ms.FUTURES_FILE,ms.NOWCAST_FILE)]
        self.assertEqual(counts,[2*len(ms.INDEX_PERPS),2,2*len(ms.FUTURES),6])
        self.assertEqual({r['slot'] for r in self.rows(ms.FUTURES_FILE)},{'close'})
        self.assertEqual((self.root/ms.PERP_FILE).read_text(encoding='utf-8').count('snapshot_utc'),1)

    def test_morning_snapshot_skips_the_nowcast(self):
        self.assertEqual(self.go(when=MORNING),0)
        self.assertEqual(self.rows(ms.NOWCAST_FILE),[])
        self.assertEqual(self.rows(ms.FUTURES_FILE)[0]['change_since_4pm_pct'],str(round((7424/7402-1)*100,4)))

    def test_waits_for_a_running_build_before_writing(self):
        self.assertEqual(self.go(busy=[True,True,False]),0)
        self.assertEqual(self.slept,[15,15]);self.assertTrue(any('waited 30s' in s for s in self.said))

    def test_scheduled_run_outside_windows_writes_nothing(self):
        self.assertEqual(self.go(when=pd.Timestamp('2026-11-09 12:00',tz=NY)),0)
        self.assertFalse((self.root/ms.PERP_FILE).exists())

    def test_each_source_fails_on_its_own(self):
        def no_book(path,params=None):
            if path.endswith('/orderbook'):raise RuntimeError('timeout')
            return fake_get(path,params)
        def no_nowcast():raise OSError('offline')
        self.assertEqual(self.go(get=no_book,nowcast=no_nowcast),1)
        perps=self.rows(ms.PERP_FILE)
        self.assertEqual((len(perps),perps[0]['bid'],perps[0]['bid_depth_5bp_usd']),(len(ms.INDEX_PERPS),'13.0',''))
        self.assertEqual(len(self.rows(ms.FUTURES_FILE)),len(ms.FUTURES))
        self.assertTrue(any('order book: timeout' in s and 'nowcast: offline' in s for s in self.said))

    def test_kalshi_down_still_records_futures(self):
        def down(path,params=None):raise RuntimeError('503')
        self.assertEqual(self.go(get=down),1)
        self.assertEqual((len(self.rows(ms.PERP_FILE)),len(self.rows(ms.FUTURES_FILE))),(0,len(ms.FUTURES)))


if __name__=='__main__':unittest.main()
