"""Second-source price check: FRED parsing, download fallback, daily-return gaps, quality row."""
import tempfile, unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd

import crosscheck as cc

ROOT=Path(__file__).resolve().parents[1]
SCRATCH=ROOT/'work'/'crosscheck_tests'
SCRATCH.mkdir(parents=True,exist_ok=True)
DAYS=pd.bdate_range('2026-01-02',periods=300)


def fred_csv(series,values,days=DAYS):
    return f'observation_date,{series}\n'+''.join(f'{d:%Y-%m-%d},{v}\n' for d,v in zip(days,values))


def closes(start=100.0,seed=1):
    returns=np.random.default_rng(seed).normal(0,0.01,len(DAYS))
    return pd.Series(start*np.cumprod(1+returns),index=DAYS)


class ParseAndRefreshTests(unittest.TestCase):
    def test_parse_skips_fred_holiday_dots(self):
        s=cc.parse('observation_date,SP500\n2026-01-01,.\n2026-01-02,6000.5\n2026-01-05,6010\n')
        self.assertEqual(list(s.index.strftime('%Y-%m-%d')),['2026-01-02','2026-01-05']);self.assertEqual(s.iloc[-1],6010.0)

    def test_refresh_saves_good_downloads_and_keeps_old_copy_on_failure(self):
        with tempfile.TemporaryDirectory(dir=SCRATCH) as tmp:
            root=Path(tmp);good=fred_csv('SP500',closes())
            def get(url,headers=None,timeout=None):
                if 'NASDAQ100' in url:raise OSError('offline')
                return SimpleNamespace(text=good,raise_for_status=lambda:None)
            (root/cc.FOLDER).mkdir(parents=True);(root/cc.FOLDER/'NASDAQ100.csv').write_text(good,encoding='utf-8')
            status=cc.refresh(root,get=get)
            self.assertEqual((status['SP500']['ok'],status['NASDAQ100']['ok']),(True,False))
            self.assertEqual(set(cc.load(root)),{'SP500','NASDAQ100'})  # the old Nasdaq copy survives


class CompareTests(unittest.TestCase):
    def setUp(self):
        self.spx=closes(6000.0,1);self.ndx=closes(20000.0,2)
        self.table=pd.DataFrame({'spy_ret':self.spx.pct_change(),'qqq_ret':self.ndx.pct_change()})

    def test_matching_returns_pass(self):
        report=cc.compare(self.table,{'SP500':self.spx,'NASDAQ100':self.ndx})
        self.assertEqual({r['status'] for r in report.values()},{'PASS'})
        self.assertEqual(report['SP500']['compared'],cc.WINDOW)
        self.assertEqual(cc.quality_row(report)[2],'PASS')

    def test_a_bad_print_is_flagged_with_its_date(self):
        table=self.table.copy();bad=DAYS[-5];table.loc[bad,'spy_ret']+=0.01
        report=cc.compare(table,{'SP500':self.spx,'NASDAQ100':self.ndx})
        self.assertEqual(report['SP500']['status'],'CHECK')
        self.assertEqual(report['SP500']['flagged'],[{'date':str(bad.date()),'gap_pct':1.0}])
        row=cc.quality_row(report)
        self.assertEqual(row[2],'CHECK');self.assertIn(f'SPY {bad.date()} (+1.00%)',row[3])

    def test_missing_series_is_unavailable_not_failed(self):
        report=cc.compare(self.table,{'SP500':self.spx})
        self.assertEqual((report['SP500']['status'],report['NASDAQ100']['status']),('PASS','UNAVAILABLE'))
        self.assertEqual(cc.quality_row(report)[2],'PARTIAL')
        self.assertEqual(cc.quality_row(cc.compare(self.table,{}))[2],'UNAVAILABLE')


if __name__=='__main__':unittest.main()
