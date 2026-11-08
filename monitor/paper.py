"""Append-only research decisions; no retrospective creation of forward results."""
from __future__ import annotations
import hashlib,json,os
from datetime import datetime,timezone
from pathlib import Path
import pandas as pd
from .backtest import STRATEGIES,signal_mask,timestamp,trade_result,config_hash


def sha(obj):return hashlib.sha256(json.dumps(obj,sort_keys=True).encode()).hexdigest()


def read_log(path):
    if not path.exists():return []
    events=[json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]
    previous=''
    for item in events:
        payload={k:v for k,v in item.items() if k!='hash'}
        if item.get('previous_hash')!=previous or item.get('hash')!=sha(payload):raise ValueError('Paper log hash chain failed; do not overwrite it')
        previous=item['hash']
    return events


def append(path,events,event):
    payload={**event,'previous_hash':events[-1]['hash'] if events else ''}
    row={**payload,'hash':sha(payload)}
    path.parent.mkdir(parents=True,exist_ok=True)
    # One local builder holds the refresh lock. Readers verify the complete chain.
    with path.open('a',encoding='utf-8') as f:f.write(json.dumps(row,sort_keys=True)+'\n')
    events.append(row)


def update(root,t,costs,quality_ok,run_id):
    from validation import equity_sessions
    folder=root/'data/monitor'
    readonly=os.environ.get('APP_OFFLINE')=='1' or os.environ.get('APP_REPLAY')=='1'
    if not readonly:folder.mkdir(parents=True,exist_ok=True)
    lock=folder/'experiment_lock.json'
    if lock.exists():
        experiment=json.loads(lock.read_text(encoding='utf-8'))
    else:
        experiment={'created_utc':datetime.now(timezone.utc).isoformat(),'strategies':STRATEGIES,'costs':costs,
                    'cost_hash':config_hash(costs),'version':'corrected-next-open-v1',
                    'description':'Frozen research rules; forward decisions are recorded before hypothetical next-open entries.'}
        if not readonly:lock.write_text(json.dumps(experiment,indent=2),encoding='utf-8')
    path=folder/'paper_events.jsonl';events=read_log(path)
    replay=readonly
    now=pd.Timestamp.now(tz='UTC')
    key_prefix=experiment['version']+':'+str(t.index[-1].date())
    sessions=equity_sessions(t.index[-1],t.index[-1]+pd.Timedelta(days=35))
    after=sessions[sessions>t.index[-1]]
    decisions={e['key']:e for e in events if e['type']=='decision'}
    for rule in experiment['strategies']:
        key=key_prefix+':'+rule['id']
        if key in decisions or replay:continue
        start=timestamp(after[0],9,30);end=timestamp(after[rule['horizon']-1],16)
        signal=bool(signal_mask(t,rule).iloc[-1]) if quality_ok else False
        state='recorded_before_entry' if now<start.tz_convert('UTC') and quality_ok else 'late_unscored' if now>=start.tz_convert('UTC') else 'data_blocked'
        if any(e['strategy']==rule['id'] and e.get('signal') and e['state']=='recorded_before_entry' and pd.Timestamp(e['exit_at'])>start for e in decisions.values()):
            state='overlap_skipped';signal=False
        append(path,events,{'type':'decision','key':key,'strategy':rule['id'],'name':rule['name'],
                          'signal_date':str(t.index[-1].date()),'signal':signal,'side':rule['side'] if signal else 0,
                          'recorded_at':now.isoformat(),'entry_at':start.isoformat(),'exit_at':end.isoformat(),
                          'state':state,'run_id':run_id,'cost_hash':experiment['cost_hash'],
                          'features':{'day_type':str(t['spy_day_type'].iloc[-1]),'vix':float(t['vix'].iloc[-1])}})
    outcomes={e['key']:e for e in events if e['type']=='outcome'}
    decisions={e['key']:e for e in events if e['type']=='decision'}
    for key,d in list(decisions.items()):
        if key in outcomes or d['state']!='recorded_before_entry':continue
        end=pd.Timestamp(d['exit_at']);start=pd.Timestamp(d['entry_at'])
        a=start.tz_localize(None).normalize();b=end.tz_localize(None).normalize()
        if now<end.tz_convert('UTC') or b>t.index[-1] or a not in t.index or b not in t.index:continue
        if not d['signal']:
            result={'gross':0.0,'net':0.0,'reason':'No-edge abstention; no hypothetical position.'}
        else:
            result=trade_result(float(t.loc[a,'spy_open']),float(t.loc[b,'spy_close']),d['side'],start,end,experiment['costs'])
        if not replay:append(path,events,{'type':'outcome','key':key,'strategy':d['strategy'],'observed_at':now.isoformat(),'run_id':run_id,**result})
    return {'experiment':experiment,'events':events,'replay':replay,'path':str(path.relative_to(root)),
            'config_changed':config_hash(costs)!=experiment['cost_hash'],'chain_verified':True}
