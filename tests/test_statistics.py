import unittest, tempfile, os, json
from pathlib import Path
from unittest.mock import patch
import numpy as np
import pandas as pd
from stage1.studies import forward_return,normalized_wealth,adjust_pvalues,Judge,daily_reset_return
from tickers.build import overnight_split,_ret
from monitor.backtest import trade_result,validate_costs,simulate,STRATEGIES
from monitor.employment import validated_surprises,parse_release,parse_calendar
from monitor import paper

class RegressionTests(unittest.TestCase):
    def test_missing_middle_does_not_compress_sessions(self):
        c=pd.Series([100,np.nan,104,105],index=pd.bdate_range('2020-01-02',periods=4))
        self.assertTrue(np.isnan(forward_return(c,1).iloc[0]))
        self.assertAlmostEqual(forward_return(c,2).iloc[0],.04)
        self.assertTrue(np.isnan(_ret(c.iloc[:3],1)))
        self.assertAlmostEqual(normalized_wealth(c).iloc[2],1.04)

    def test_common_sample_decomposition(self):
        t=pd.DataFrame({'spy_overnight':[.01,np.nan,.02],'spy_daytime':[.02,np.nan,-.01],
                        'spy_ret':[1.01*1.02-1,.05,1.02*.99-1],'spy_close':[103.02,108.171,109.23],
                        'spy_flag':['','open = prior close (unconfirmed)','']},index=pd.bdate_range('2020-01-02',periods=3))
        s=overnight_split(t,'SPY')
        self.assertAlmostEqual(s['growth_all'].iloc[-1],s['growth_on'].iloc[-1]*s['growth_day'].iloc[-1])

    def test_reset_path_benchmark(self):
        c=pd.Series([100.,110.,100.])
        expected=(1+3*.1)*(1+3*(100/110-1))-1
        self.assertAlmostEqual(daily_reset_return(c,2,3).iloc[0],expected)

    def test_multiple_testing_corrections(self):
        r=adjust_pvalues([{'p':.001},{'p':.02},{'p':.2}])
        self.assertAlmostEqual(r[0]['p_holm'],.003)
        self.assertGreaterEqual(r[1]['p_bh'],.02)
        r=adjust_pvalues([{'p':None},{'p':.01}])
        self.assertNotIn('p_bh',r[0])
        self.assertAlmostEqual(r[1]['p_bh'],.01)

    def test_costs_charge_both_sides_and_calendar_funding(self):
        c=validate_costs({'half_spread_bps':0,'slippage_bps_per_side':0,'fee_bps_per_side':2,'funding_bps_per_calendar_day':1})
        start=pd.Timestamp('2026-01-02T16:00:00Z');end=start+pd.Timedelta(days=3)
        r=trade_result(100,100,1,start,end,c)
        self.assertAlmostEqual(r['net'],-.0007)
        self.assertAlmostEqual(trade_result(100,100,-1,start,end,c)['net'],-.0001)

    def test_no_future_completed_trade(self):
        t=pd.DataFrame({'spy_open':[100]*3,'spy_close':[100,101,102],'spy_day_type':['normal drop']*3,'vix':[20]*3},index=pd.bdate_range('2026-01-02',periods=3))
        tr,_,stats=simulate(t,STRATEGIES[2],validate_costs({}))
        self.assertEqual(stats['trades'],0)

    def test_consensus_after_release_is_rejected(self):
        release=[{'metric':'payroll','reference_period':'2026-10','actual':100,'available_at':'2026-11-06T13:30:00Z'}]
        future=[{'metric':'payroll','reference_period':'2026-10','consensus':90,'available_at':'2026-11-06T13:31:00Z'}]
        self.assertEqual(validated_surprises(release,future),[])
        future[0]['available_at']='2026-11-06T13:29:00Z'
        self.assertEqual(validated_surprises(release,future)[0]['surprise'],10)

    def test_bls_parse_missing_values_stay_missing(self):
        r=parse_release('<h1>The Employment Situation -- October 2026</h1><p>Total nonfarm payroll employment increased by 100,000. The unemployment rate was 4.2 percent.</p>')
        self.assertEqual(r['payroll_change'],100000)
        self.assertIsNone(r['wage_change_mom_pct'])

    def test_paper_log_detects_tampering(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]/'work') as folder:
            p=Path(folder)/'log.jsonl';events=[]
            paper.append(p,events,{'type':'decision','key':'first','signal':True})
            self.assertEqual(len(paper.read_log(p)),1)
            text=p.read_text().replace('"signal": true','"signal": false');p.write_text(text)
            with self.assertRaises(ValueError):paper.read_log(p)

    def test_offline_replay_never_creates_forward_records(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]/'work') as folder:
            t=pd.DataFrame({'spy_day_type':['big rise'],'vix':[25]},index=pd.DatetimeIndex(['2026-11-05']))
            with patch.dict(os.environ,{'APP_OFFLINE':'1'}):state=paper.update(Path(folder),t,validate_costs({}),True,'test')
            self.assertEqual(state['events'],[])
            self.assertFalse((Path(folder)/'data/monitor/paper_events.jsonl').exists())

if __name__=='__main__':unittest.main()
