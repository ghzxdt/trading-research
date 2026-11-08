"""Run one code version in a separate process against the same cached market inputs."""
from __future__ import annotations
import argparse, json, sys, warnings
from pathlib import Path
import numpy as np
import pandas as pd


def clean(v):
    if isinstance(v,dict):return {str(k):clean(x) for k,x in v.items()}
    if isinstance(v,(list,tuple)):return [clean(x) for x in v]
    if isinstance(v,np.ndarray):return clean(v.tolist())
    if isinstance(v,(pd.Timestamp,Path)):return str(v)
    if isinstance(v,(np.bool_,)):return bool(v)
    if isinstance(v,(np.integer,)):return int(v)
    if isinstance(v,(float,np.floating)):return float(v) if np.isfinite(v) else None
    return v


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--code-root',required=True);ap.add_argument('--data-root',required=True);ap.add_argument('--out',required=True)
    a=ap.parse_args();code=Path(a.code_root);data=Path(a.data_root)
    sys.path.insert(0,str(code));warnings.filterwarnings('ignore')
    from stage1 import sources,dataset,studies
    from tickers import build as tickers
    from leverage import build as leverage,kalshi
    from gex import data as gd,build as gb
    sources.RAW=data/'data/raw';sources.EVENTS_FILE=data/'data/events/events.csv'
    # The baseline's calendar semantics are frozen, even when a new calendar has extra metadata.
    raw=sources.fetch_all(offline=True);t,_=dataset.build(raw);long=dataset.build_long(raw)
    original_judge=studies.Judge
    captured=[]
    class Capture(original_judge):
        def test(self,*args,**kwargs):
            r=super().test(*args,**kwargs);captured.append(r.copy());return r
    studies.Judge=Capture
    reports,count=studies.run_all(t,long)
    dix=gd.load_dix(data/'data/manual/DIX.csv')
    if dix is not None:
        gx=gb.study_history(gd.joined(t,dix),Capture())
        reports.append(gx)
    p=t['spy_close'];nxt=t['spy_ret'].shift(-1);big=t['spy_day_type'].eq('big rise');covid=pd.Series((t.index>='2020-02-15')&(t.index<='2020-06-30'),index=t.index)
    metrics={'as_of':str(t.index[-1].date()),'rows':len(t),'test_count':len(captured),
             'SPXU_first_return':float(t['spxu_ret'].iloc[0]),
             'rally_next_mean':float(nxt[big].mean()),'rally_next_ex_covid':float(nxt[big&~covid].mean()),
             'high_vix_rally_next':float(nxt[big&t.vix.ge(20)].mean()),
             'high_vix_rally_ex_covid':float(nxt[big&t.vix.ge(20)&~covid].mean())}
    for tk in ('SPY','QQQ','SPXU'):
        s=tickers.overnight_split(t,tk)
        for field in ('share','growth_all','growth_on','growth_day','growth_buy_hold'):
            if field not in s:continue
            value=s[field]
            metrics[tk+'_'+field]=float(value.dropna().iloc[-1]) if isinstance(value,pd.Series) else float(value)
    # Pure invalid-input probe; no API request and no account access.
    missing=leverage._hit_rates(long,'SPY',np.nan)
    metrics['missing_margin_long_hit_rate']=missing.get('long_1')
    result={'metrics':metrics,'tests':captured,'studies':reports}
    Path(a.out).write_text(json.dumps(clean(result),allow_nan=False),encoding='utf-8')
    print('Probe complete:',code.name,len(captured),'tests')

if __name__=='__main__':main()
